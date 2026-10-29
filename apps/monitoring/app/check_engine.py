# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Check engine: runs checks, updates states, writes metrics.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy.orm import Session

from app.alerter import process_alert, resolve_notification
from app.check_types import PUSH_ONLY_TYPES
from app.checkers import get_checker
from app.core import database
from app.core.time import utcnow_naive
from app.core.victoria import victoria
from app.models import MonitorCheck, MonitorState

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
    """Counts consecutive failures. 'ok' resets to 0.

    POLICY NOTE: any non-'ok' status increments the counter, including
    'unknown' (e.g. "waiting for agent data", or an SSRF-blocked target), so a
    persistently-unknown check still becomes visible as such on the dashboard
    after ``consecutive_fails`` occurrences. Notifications are decided
    elsewhere: transitions INTO 'unknown' are deliberately never dispatched —
    neither rules nor hub (guard in process_alert); real "agent gone" is the
    persisted agent_ping check going critical.
    """
    if result_status != "ok":
        return prev_fail_count + 1
    return 0


def is_suppressed(result_status: str, new_fail_count: int, consecutive_fails: int) -> bool:
    """True as long as a non-OK result has not yet reached the required number
    of consecutive failures."""
    return result_status != "ok" and new_fail_count < consecutive_fails


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


def next_ok_count(result_status: str, prev_ok_count: int) -> int:
    """Counts consecutive 'ok' results — the counterpart of next_fail_count.
    Any other status resets to 0."""
    if result_status == "ok":
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
    if result_status != "ok" or notified_status not in ("warning", "critical"):
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
) -> tuple[str, str, str]:
    """Write one check result into its MonitorState and decide on notification.

    The read-modify-write both result paths share: damping (next_fail_count /
    effective_status), the recovery hold (next_ok_count / holds_recovery) and the
    sent-state decision; the transition's log line is the caller's, after its commit
    (log_transition). It used to exist twice — here for the scheduler and as a hand-kept copy in
    routers/agent.py — which is exactly the duplicate truth that drifts (B3).

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

    # Alerting on a DISCREPANCY to the last reported status, not on the raw
    # transition (sent-state, alert-sent-state T4): once a suppression
    # (maintenance/host-down) is gone, the next cycle catches the pending
    # report up even though the status itself did not change. A silent_ack
    # (an ok that never had a reported problem) is pure bookkeeping and is
    # recorded inline — no BG task. process_alert re-checks the decision
    # under FOR UPDATE, so a stale read here only costs a no-op task.
    decision = resolve_notification(state.notified_status, eff_status)
    if decision == "silent_ack":
        state.notified_status = eff_status
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


def execute_check(check_id: str) -> None:
    """Called by the scheduler for each check interval."""
    db = database.SessionLocal()
    try:
        check = (
            db.query(MonitorCheck)
            .filter(MonitorCheck.id == check_id, MonitorCheck.enabled == True)  # noqa: E712
            .first()
        )
        if not check:
            return

        try:
            config = json.loads(check.config) if check.config else {}
        except (json.JSONDecodeError, TypeError):
            config = None

        # Do not run push-only checks from the scheduler
        if check.check_type in PUSH_ONLY_TYPES:
            return

        check_type, server_id, name = check.check_type, check.server_id, check.name
        config = resolve_config_server_id(config, check_type, server_id)

        checker = None
        if config is not None:
            try:
                checker = get_checker(check_type)
            except ValueError as exc:
                logger.warning("Check %s: %s", name, exc)

        # End the read transaction before the run: the checker takes up to its configured
        # timeout (at most 300 s) and the metric write follows. Held over both, the 30
        # scheduler workers (scheduler.py) could take all 30 pool connections
        # (core/database.py) whenever a target or VictoriaMetrics hangs, and agent reports
        # and API requests would fail (R-0615). The rollback expires `check`; until it is
        # read again below, only the values taken above are used.
        db.rollback()

        # A corrupt config or an unknown check type must surface as unknown so the normal alert
        # chain fires — not silently freeze the state on its last value (a "dead" check that still
        # looks healthy, with no alert and no dashboard hint) (4.109).
        start = time.monotonic()
        if config is None:
            result_status, message, metrics = "unknown", "Invalid check configuration", None
        elif checker is None:
            result_status, message, metrics = "unknown", "Unknown check type", None
        else:
            try:
                result_status, message, metrics = checker.run(config)
            except Exception as exc:
                result_status = "unknown"
                message = f"Unexpected error: {exc}"
                metrics = None
                logger.exception("Check %s fehlgeschlagen", name)
        duration_ms = int((time.monotonic() - start) * 1000)

        # Extract structured details (not sent to VictoriaMetrics)
        details = metrics.pop("_details", None) if metrics else None

        now = utcnow_naive()

        # Send metrics to VictoriaMetrics
        victoria.write_check_result(
            check_id=check_id,
            check_type=check_type,
            server_id=server_id,
            name=name,
            status=result_status,
            duration_ms=duration_ms,
            extra_metrics=metrics,
        )

        # Update state. Lock the row for the read-modify-write (fail_count, status): the
        # scheduler's max_instances=1 isn't the only writer — POST /checks/{id}/run runs the same
        # check synchronously on the request thread, and the agent push path can fire two
        # near-simultaneous reports for one server. Without the lock both could read fail_count=2
        # and write 3 instead of 4, or both see the same transition and double-alert (4.46).
        # with_for_update is a no-op on sqlite (tests); the real lock is on Postgres.
        state = (
            db.query(MonitorState)
            .filter(MonitorState.check_id == check_id)
            .with_for_update()
            .first()
        )
        # Read again: the check may have been changed or deleted during the run.
        check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
        if check is None:
            logger.debug("Check %s was deleted during its run, result dropped", check_id)
            return
        had_state = state is not None
        check_name = check.name
        old_status, eff_status, decision = apply_result(
            db, check, state, result_status, message, details, now
        )
        # The message as stored (capped, with the damping suffix), read before the commit
        # expires the row.
        stored_message = state.message if had_state else message
        db.commit()
        if had_state and eff_status != old_status:
            log_transition(check_name, old_status, eff_status, stored_message)

        # Dispatch OFF the check-worker thread (see _alert_pool /
        # dispatch_alert_bg) so a slow webhook/SMTP server can't stall the
        # scheduler pool and misfire following checks. Pass the id, not the
        # session-bound check — the pool thread reloads it in its own session (5.3).
        # A heartbeat's discrepancy stays open for the agent alert bundle
        # (alert_bundle.flush_agent_alerts), which reports agents that go silent
        # or come back together in one message.
        if decision == "notify" and check_type != "agent_ping":
            _alert_pool.submit(dispatch_alert_bg, check_id, old_status, eff_status)

    except Exception:
        logger.exception("execute_check(%s) fehlgeschlagen", check_id)
        db.rollback()
    finally:
        db.close()
