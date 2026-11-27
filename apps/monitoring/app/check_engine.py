# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Check engine: runs checks, updates states, writes metrics.
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.alerter import alert_status, process_alert, resolve_notification
from app.central.limits import RunSkipped
from app.check_types import PUSH_ONLY_TYPES
from app.checkers import CheckContext, Checker, PartnerState, get_checker
from app.checkers.agent import NO_RATING, exact_patterns, exclusions
from app.checkers.context import DiskRules
from app.core import database
from app.core.bounds import storable
from app.core.time import utcnow_naive
from app.core.victoria import victoria
from app.exception_scope import load_no_rating, runs
from app.models import MonitorCheck, MonitorState, MonitorStatusChange

logger = logging.getLogger("monitor.engine")

# Alerts are dispatched OFF the APScheduler check-worker thread via this small pool: a slow/hung
# webhook or SMTP server (up to 10s each, serial) would otherwise tie up the check workers and
# misfire the next checks — exactly during an incident when many checks transition at once. Same
# isolation the agent push path needs too — since harness 8a T4 both paths share
# the one dispatch_alert_bg below, each scheduling it its own way (5.3).
_alert_pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="alert")

# Longest message apply_result stores, the "…" included. The checkers cap what they copy
# from a report (MAX_AGENT_TEXT, join_capped), but a message with two full lists or a
# scheduler check's "Unexpected error: {exc}" can still be longer, and the message goes
# from MonitorState.message into the transition log, webhook and mail. Four agent texts
# of 500 (R-0517).
MAX_MESSAGE = 2000

# The note a skipped central run leaves behind the message; the next one replaces it.
_SKIP_NOTE = re.compile(r" \(skipped: [^()]*\)\Z")

# info is a hint without an alarm (R-1280): it counts like ok for damping and the recovery hold.
_HEALTHY = ("ok", "info")

# "Not collected": an object nothing was measured of (app.objects). It exists only in the
# object state; the check's own status keeps the vocabulary MonitorStateOut has always had
# (Kevin 2026-11-19), so a check result of it is stored as ok.
NOT_COLLECTED = "not_collected"


def dispatch_alert_bg(check_id: str, old_status: str, new_status: str) -> None:
    """Dispatch one alert (webhook/SMTP) with its own session.

    The single dispatcher for both paths: the scheduler submits it to
    ``_alert_pool``, the agent push path schedules it via BackgroundTasks. Either
    way the caller's session is already closed by the time this runs, so it
    reloads the check. Errors are contained — a failed dispatch must never bubble
    out of the pool thread or surface to a reporting agent.

    The factory is reached as ``database.SessionLocal`` — the module attribute,
    never a name imported into this one. That is the single patch point for both
    paths; two idioms in one file would mean a test that patches the wrong one
    silently opens a connection to the real DATABASE_URL and, because every
    exception here is swallowed, stays green while the alert path never ran.
    """
    db = database.SessionLocal()
    try:
        check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
        if check is None:
            return
        process_alert(db, check, old_status, new_status)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Alert-Dispatch fuer Check %s fehlgeschlagen", check_id)
    finally:
        db.close()


def next_fail_count(result_status: str, prev_fail_count: int) -> int:
    """Counts consecutive failures. 'ok' and 'info' reset to 0.

    POLICY NOTE: any other status increments the counter, including
    'unknown' (e.g. "waiting for agent data", or an SSRF-blocked target), so a
    persistently-unknown check still becomes visible as such on the dashboard
    after ``consecutive_fails`` occurrences. Notifications are decided
    elsewhere: transitions INTO 'unknown' are deliberately never dispatched —
    neither rules nor hub (guard in process_alert); real "agent gone" is the
    persisted agent_ping check going critical.
    """
    if result_status not in _HEALTHY:
        return prev_fail_count + 1
    return 0


def is_suppressed(result_status: str, new_fail_count: int, consecutive_fails: int) -> bool:
    """True as long as a non-OK result has not yet reached the required number
    of consecutive failures."""
    return result_status not in _HEALTHY and new_fail_count < consecutive_fails


def effective_status(
    result_status: str,
    new_fail_count: int,
    consecutive_fails: int,
    old_status: str,
) -> str:
    """Determines the effective status, taking consecutive_fails into account.

    As long as a non-OK result has not yet reached the required number of
    consecutive failures, the previous status is kept ('pending' is treated
    as 'ok' here, except for an 'unknown' result). Otherwise the raw result
    applies.
    """
    if is_suppressed(result_status, new_fail_count, consecutive_fails):
        if old_status != "pending":
            return old_status
        # A new check without data must not stand green (R-0419). Passing unknown
        # through costs no alert — unknown never notifies; a first warning or
        # critical stays damped.
        return "unknown" if result_status == "unknown" else "ok"
    return result_status


def damp_object(
    result_status: str,
    prev_fail_count: int,
    consecutive_fails: int,
    old_status: str,
    reason: str,
) -> tuple[str, int, str]:
    """(effective status, fail count, reason with its damping suffix) of one object of a
    result (app.objects), damped like its check; `old_status` is "pending" for a new one.

    Without the recovery hold: that needs a reported status per object, which comes with
    the notification per object (ADR 0004 P3). The count is capped at consecutive_fails:
    past it it decides nothing, and a count that kept rising would rewrite a failing
    object on every result. not_collected counts as healthy: nothing was measured that
    could have failed."""
    if result_status == NOT_COLLECTED:
        return NOT_COLLECTED, 0, reason
    fail_count = min(next_fail_count(result_status, prev_fail_count), consecutive_fails)
    eff_status = effective_status(result_status, fail_count, consecutive_fails, old_status)
    if is_suppressed(result_status, fail_count, consecutive_fails):
        reason = f"{reason} (failure {fail_count}/{consecutive_fails})"
    return eff_status, fail_count, reason


def next_ok_count(result_status: str, prev_ok_count: int) -> int:
    """Counts consecutive 'ok' (and 'info') results — the counterpart of
    next_fail_count. Any other status resets to 0."""
    if result_status in _HEALTHY:
        return prev_ok_count + 1
    return 0


def holds_recovery(
    result_status: str,
    new_ok_count: int,
    consecutive_oks: int,
    old_status: str,
    notified_status: str | None,
) -> bool:
    """True as long as an 'ok' result on a check that carries a reported problem
    has not yet reached the required number of consecutive oks (R-0424).

    Only a reported problem is held (Kevin 2026-10-20): the last reported status
    is warning/critical and the check still stands at warning, critical or
    unknown — a reported problem that comes back via unknown must not skip the
    hold. A problem muted by maintenance or host-down was never reported and
    recovers on the first ok, silently; holding it would catch it up as a fresh
    alert. pending -> ok and ok -> ok never hold, and consecutive_oks 1 is the
    behaviour from before the hold.
    """
    if result_status not in _HEALTHY or notified_status not in ("warning", "critical"):
        return False
    return old_status in ("warning", "critical", "unknown") and new_ok_count < consecutive_oks


def resolve_config_server_id(
    config: dict | None, check_type: str, server_id: str | None
) -> dict | None:
    """agent_ping/disk_forecast read their data source from config["server_id"].

    Template defs inject it via {{server_id}}, but a hand-created check only
    carries the column — without this fallback it would sit at 'unknown'
    forever (T37). An explicit config value always wins."""
    if (
        config is not None
        and check_type in ("agent_ping", "disk_forecast")
        and not config.get("server_id")
        and server_id
    ):
        config["server_id"] = server_id
    return config


def log_transition(name: str, old_status: str, new_status: str, message: str) -> None:
    """The log line of a status change, once the change is saved.

    Without it a transition leaves no trace at all: MonitorAlertLog only records SENT
    notifications, so one suppressed by maintenance or host-down was invisible
    afterwards. Both result paths call it after their commit, so a change that a
    failed commit discards is not logged."""
    logger.info("Check '%s': %s -> %s (%s)", name, old_status, new_status, message)


def apply_result(
    db: Session,
    check: MonitorCheck,
    state: MonitorState | None,
    result_status: str,
    message: str,
    details: dict | None,
    now: datetime,
    *,
    keep_previous_details_when_absent: bool = False,
    objects: dict | None = None,
) -> tuple[str, str, str]:
    """Write one check result into its MonitorState and decide on notification.

    The read-modify-write both result paths share: damping (next_fail_count /
    effective_status), the recovery hold (next_ok_count / holds_recovery) and the
    sent-state decision. A change of the damped status also adds a row to the status
    change log (monitor_status_log), and the result's `objects` (the checker's
    `_objects`, None without) go into the object state (app.objects.apply_objects),
    both in the caller's transaction; the transition's log line is the caller's, after
    its commit (log_transition). It used to exist twice — here for the scheduler and as
    a hand-kept copy in routers/agent.py — which is exactly the duplicate truth that
    drifts (B3).

    The caller passes the already-locked `state` (None before the first result),
    then commits and dispatches: the scheduler off its own alert pool, the push
    path via BackgroundTasks after the batch commit. Note that a created state is
    bound to the session here, not handed back — the caller's own variable stays
    None on the first result of a new check, so do not read it afterwards.

    `keep_previous_details_when_absent` is the one real difference between the
    paths: the scheduler re-derives details on every run, so an empty result
    legitimately clears them; an agent report may arrive without the block at
    all, and nulling the stored details would wipe the per-metric hysteresis
    memory on one degenerate push (T38).

    Returns (old_status, effective status, notification decision).
    """
    # app.objects imports the damping from here.
    from app.objects import apply_objects

    if result_status == NOT_COLLECTED:
        result_status = "ok"
    message = storable(message)
    details = storable(details)
    old_status = state.status if state else "pending"
    eff_status, message, new_fail_count, new_ok_count = _damp(
        check, state, old_status, result_status, message
    )
    state = _write_state(
        db,
        check,
        state,
        now,
        eff_status,
        message,
        new_fail_count,
        new_ok_count,
        details,
        keep_previous_details_when_absent,
    )
    if eff_status != old_status:
        db.add(
            MonitorStatusChange(
                check_id=check.id,
                old_status=old_status,
                new_status=eff_status,
                at=now,
                origin="state",
            )
        )
    apply_objects(db, check, state, objects, now)

    # Alerting on a DISCREPANCY to the last reported status, not on the raw
    # transition (sent-state, alert-sent-state T4): once a suppression
    # (maintenance/host-down) is gone, the next cycle catches the pending
    # report up even though the status itself did not change. A silent_ack
    # (an ok that never had a reported problem) is pure bookkeeping and is
    # recorded inline — no BG task. process_alert re-checks the decision
    # under FOR UPDATE, so a stale read here only costs a no-op task.
    decision = resolve_notification(state.notified_status, eff_status)
    if decision == "silent_ack":
        state.notified_status = alert_status(eff_status)
    return old_status, eff_status, decision


def _damp(
    check: MonitorCheck,
    state: MonitorState | None,
    old_status: str,
    result_status: str,
    message: str,
) -> tuple[str, str, int, int]:
    """(effective status, message with its damping suffix, fail count, ok count)."""
    notified_status = state.notified_status if state else None
    prev_fail_count = state.fail_count if state else 0
    new_fail_count = next_fail_count(result_status, prev_fail_count)
    new_ok_count = next_ok_count(result_status, state.ok_count if state else 0)

    # Effective status, taking consecutive_fails into account.
    eff_status = effective_status(
        result_status, new_fail_count, check.consecutive_fails, old_status
    )
    # ...and consecutive_oks: a held recovery stands at the reported problem, not
    # at a worse status reached while muted — the hold must not escalate.
    held = holds_recovery(
        result_status, new_ok_count, check.consecutive_oks, old_status, notified_status
    )
    if held:
        eff_status = notified_status
    # Cut before the damping suffix, so "(failure n/m)" or "(recovery n/m)"
    # always stays visible.
    if len(message) > MAX_MESSAGE:
        message = message[: MAX_MESSAGE - 1] + "…"
    if is_suppressed(result_status, new_fail_count, check.consecutive_fails):
        message = f"{message} (failure {new_fail_count}/{check.consecutive_fails})"
    elif held:
        message = f"{message} (recovery {new_ok_count}/{check.consecutive_oks})"
    return eff_status, message, new_fail_count, new_ok_count


def _write_state(
    db: Session,
    check: MonitorCheck,
    state: MonitorState | None,
    now: datetime,
    eff_status: str,
    message: str,
    new_fail_count: int,
    new_ok_count: int,
    details: dict | None,
    keep_previous_details_when_absent: bool,
) -> MonitorState:
    """Creates the state of a check's first result or updates the existing one."""
    has_details = (details is not None) if keep_previous_details_when_absent else bool(details)
    details_json = json.dumps(details) if has_details else None

    if not state:
        state = MonitorState(
            check_id=check.id,
            status=eff_status,
            since=now,
            last_check=now,
            fail_count=new_fail_count,
            ok_count=new_ok_count,
            message=message,
            details=details_json,
        )
        db.add(state)
    else:
        if eff_status != state.status:
            state.since = now
        state.status = eff_status
        state.fail_count = new_fail_count
        state.ok_count = new_ok_count
        state.last_check = now
        state.message = message
        if has_details or not keep_previous_details_when_absent:
            state.details = details_json
    return state


def _json_object(text: str | None) -> dict | None:
    """A stored JSON text as a mapping; None for none, broken JSON or a non-object."""
    try:
        value = json.loads(text) if text else None
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _load_context(db: Session, check: MonitorCheck, config: dict) -> CheckContext:
    """The previous details of `check` and the state of its partner (`pair_check_id`).

    Only an enabled probe check of the same server counts as partner: the pair
    explains a central result by the agent's view of the same service, and a check
    of another server, or a disabled one with a stale state, explains nothing.
    """
    row = db.query(MonitorState.details).filter(MonitorState.check_id == check.id).first()
    prev_details = _json_object(row[0]) if row else None

    partner = None
    pair_id = config.get("pair_check_id")
    if isinstance(pair_id, str) and pair_id and check.server_id is not None:
        pair = (
            db.query(MonitorCheck)
            .filter(
                MonitorCheck.id == pair_id,
                MonitorCheck.check_type == "probe",
                runs,
                MonitorCheck.server_id == check.server_id,
            )
            .first()
        )
        if pair is not None:
            pair_state = db.query(MonitorState).filter(MonitorState.check_id == pair.id).first()
            sensor = (_json_object(pair.config) or {}).get("sensor")
            partner = PartnerState(
                check_id=pair.id,
                sensor=sensor if isinstance(sensor, str) else None,
                status=pair_state.status if pair_state else "pending",
                details=_json_object(pair_state.details) if pair_state else None,
                last_check=pair_state.last_check if pair_state else None,
            )
    disk_rules = None
    if check.check_type == "disk_forecast":
        disk_rules = _load_disk_rules(db, config.get("server_id"))
    return CheckContext(prev_details=prev_details, partner=partner, disk_rules=disk_rules)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _load_disk_rules(db: Session, server_id) -> DiskRules | None:
    """The disk rules of `server_id`'s running agent_resources check (the lowest id, as
    history.server_thresholds picks it) and the free GB per mount from its last result.
    None without such a check: the forecast then rates every mount as before."""
    if not isinstance(server_id, str) or not server_id:
        return None
    resources = (
        db.query(MonitorCheck)
        .filter(
            MonitorCheck.server_id == server_id,
            MonitorCheck.check_type == "agent_resources",
            runs,
        )
        .order_by(MonitorCheck.id)
        .first()
    )
    if resources is None:
        return None
    config = _json_object(resources.config) or {}
    # The patterns the resources check excludes a mount by, as on its own run.
    config[NO_RATING] = [(e.object_pattern, e.id) for e in load_no_rating(db, resources.id)]
    ignore = exclusions(config, "ignore_mounts", exact_patterns(config.get("ignore_mounts")))
    overrides = config.get("disk_overrides")
    default_min_free = _number(config.get("disk_min_free_gb"))
    min_free = {}
    for mount, override in (overrides if isinstance(overrides, dict) else {}).items():
        value = _number(override.get("min_free_gb")) if isinstance(override, dict) else None
        if value is not None:
            min_free[mount] = value
    row = db.query(MonitorState.details).filter(MonitorState.check_id == resources.id).first()
    disks = (_json_object(row[0]) or {}).get("disks") if row else None
    free_gb = {}
    for disk in disks if isinstance(disks, list) else []:
        if isinstance(disk, dict) and isinstance(disk.get("mount"), str):
            value = _number(disk.get("free_gb"))
            if value is not None:
                free_gb[disk["mount"]] = value
    return DiskRules(
        ignore_mounts=frozenset(pattern for pattern, _ in ignore),
        min_free_gb=min_free,
        # The default of AgentResourcesConfig.disk_min_free_gb.
        default_min_free_gb=20.0 if default_min_free is None else default_min_free,
        free_gb=free_gb,
    )


def with_skip_note(message: str | None, note: str) -> str:
    """`message` with the note of a skipped run behind it, in place of an earlier note; the
    note alone for a message that is empty or only a note. Held to MAX_MESSAGE."""
    base = _SKIP_NOTE.sub("", message or "")
    if base.startswith("skipped: "):
        base = ""
    if not base:
        return note
    suffix = f" ({note})"
    if len(base) + len(suffix) > MAX_MESSAGE:
        base = base[: MAX_MESSAGE - len(suffix) - 1] + "…"
    return base + suffix


def _note_skip(db: Session, check_id: str, note: str) -> None:
    """Notes a skipped run behind the stored message and changes nothing else.

    The run did not happen: no metric, no damping step, no alert. Status, since,
    last_check and details stay, so the age of last_check shows how long the check
    has gone unmeasured, and a skip never raises the alarm the limits exist to spare.
    """
    state = (
        db.query(MonitorState).filter(MonitorState.check_id == check_id).with_for_update().first()
    )
    if state is None:
        return
    state.message = with_skip_note(state.message, note)
    db.commit()
    logger.info("Check %s %s", check_id, note)


class _Run(NamedTuple):
    """What execute_check takes from the check before it ends the read transaction."""

    check_type: str
    server_id: str | None
    name: str
    config: dict | None
    checker: Checker | None
    context: CheckContext | None


def _load_run(db: Session, check_id: str) -> _Run | None:
    """The running check with its config, checker and context; None when the scheduler
    has nothing to run (the check is gone, switched off, skipped or push-only)."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id, runs).first()
    if not check:
        return None

    try:
        config = json.loads(check.config) if check.config else {}
    except (json.JSONDecodeError, TypeError):
        config = None
    # A stored list or number is as corrupt as broken JSON: every checker reads a mapping.
    if not isinstance(config, dict):
        config = None

    # Do not run push-only checks from the scheduler
    if check.check_type in PUSH_ONLY_TYPES:
        return None

    check_type, server_id, name = check.check_type, check.server_id, check.name
    config = resolve_config_server_id(config, check_type, server_id)

    checker = None
    context = None
    if config is not None:
        try:
            checker = get_checker(check_type)
        except ValueError as exc:
            logger.warning("Check %s: %s", name, exc)
        # Read in this transaction, before execute_check's rollback ends it.
        if getattr(checker, "wants_context", False) is True:
            context = _load_context(db, check, config)
    return _Run(check_type, server_id, name, config, checker, context)


def _run_checker(run: _Run) -> tuple[str, str, dict | None, int]:
    """Status, message, metrics and duration in ms of one run. RunSkipped passes through:
    the run did not happen."""
    # A corrupt config or an unknown check type must surface as unknown so the normal alert
    # chain fires — not silently freeze the state on its last value (a "dead" check that still
    # looks healthy, with no alert and no dashboard hint) (4.109).
    start = time.monotonic()
    if run.config is None:
        result_status, message, metrics = "unknown", "Invalid check configuration", None
    elif run.checker is None:
        result_status, message, metrics = "unknown", "Unknown check type", None
    else:
        try:
            if run.context is not None:
                result_status, message, metrics = run.checker.run_with_context(
                    run.config, run.context
                )
            else:
                result_status, message, metrics = run.checker.run(run.config)
        except RunSkipped:
            raise
        except Exception as exc:
            result_status = "unknown"
            message = f"Unexpected error: {exc}"
            metrics = None
            logger.exception("Check %s fehlgeschlagen", run.name)
    duration_ms = int((time.monotonic() - start) * 1000)
    return result_status, message, metrics, duration_ms


def lock_state(db: Session, check_id: str) -> MonitorState | None:
    """The check's state row under FOR UPDATE, held until the caller's commit; None
    before its first result."""
    query = db.query(MonitorState).filter(MonitorState.check_id == check_id).with_for_update()
    state = query.first()
    if state is None:
        # Before the first result there is no row to lock: the check's row stands in,
        # so a second first result waits here and then finds the state the first one
        # created (read again: a new statement sees what committed meanwhile).
        db.query(MonitorCheck.id).filter(MonitorCheck.id == check_id).with_for_update().first()
        state = query.first()
    return state


def _apply_locked(
    db: Session,
    check_id: str,
    result_status: str,
    message: str,
    details: dict | None,
    now: datetime,
    objects: dict | None = None,
) -> tuple[str, str, str] | None:
    """Applies one result to the locked state row and commits; apply_result's (old status,
    effective status, decision), or None when the check was deleted during its run."""
    # Lock the row for the read-modify-write (fail_count, status): the scheduler's
    # max_instances=1 isn't the only writer — POST /checks/{id}/run runs the same check
    # synchronously on the request thread, and the agent push path can fire two
    # near-simultaneous reports for one server. Without the lock both could read fail_count=2
    # and write 3 instead of 4, or both see the same transition and double-alert (4.46).
    # with_for_update is a no-op on sqlite (tests); the real lock is on Postgres.
    state = lock_state(db, check_id)
    # Read again: the check may have been changed or deleted during the run.
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if check is None:
        logger.debug("Check %s was deleted during its run, result dropped", check_id)
        return None
    had_state = state is not None
    check_name = check.name
    old_status, eff_status, decision = apply_result(
        db, check, state, result_status, message, details, now, objects=objects
    )
    # The message as stored (capped, with the damping suffix), read before the commit
    # expires the row.
    stored_message = state.message if had_state else message
    db.commit()
    if had_state and eff_status != old_status:
        log_transition(check_name, old_status, eff_status, stored_message)
    return old_status, eff_status, decision


def execute_check(check_id: str) -> None:
    """Called by the scheduler for each check interval: load, run, write the metrics,
    apply the result, notify."""
    db = database.SessionLocal()
    try:
        run = _load_run(db, check_id)
        if run is None:
            return

        # End the read transaction before the run: the checker takes up to its configured
        # timeout (at most 300 s) and the metric write follows. Held over both, the 30
        # scheduler workers (scheduler.py) could take all 30 pool connections
        # (core/database.py) whenever a target or VictoriaMetrics hangs, and agent reports
        # and API requests would fail (R-0615). The rollback expires the check; until
        # _apply_locked reads it again, only the values in `run` are used.
        db.rollback()

        try:
            result_status, message, metrics, duration_ms = _run_checker(run)
        except RunSkipped as skip:
            _note_skip(db, check_id, str(skip))
            return

        # Extract structured details and objects (not sent to VictoriaMetrics)
        details = metrics.pop("_details", None) if metrics else None
        objects = metrics.pop("_objects", None) if metrics else None

        now = utcnow_naive()

        victoria.write_check_result(
            check_id=check_id,
            check_type=run.check_type,
            server_id=run.server_id,
            name=run.name,
            status=result_status,
            duration_ms=duration_ms,
            extra_metrics=metrics,
        )

        applied = _apply_locked(db, check_id, result_status, message, details, now, objects)
        if applied is None:
            return
        old_status, eff_status, decision = applied

        # Dispatch OFF the check-worker thread (see _alert_pool /
        # dispatch_alert_bg) so a slow webhook/SMTP server can't stall the
        # scheduler pool and misfire following checks. Pass the id, not the
        # session-bound check — the pool thread reloads it in its own session (5.3).
        # A heartbeat's discrepancy stays open for the agent alert bundle
        # (alert_bundle.flush_agent_alerts), which reports agents that go silent
        # or come back together in one message.
        if decision == "notify" and run.check_type != "agent_ping":
            _alert_pool.submit(dispatch_alert_bg, check_id, old_status, eff_status)

    except Exception:
        logger.exception("execute_check(%s) fehlgeschlagen", check_id)
        db.rollback()
    finally:
        db.close()
