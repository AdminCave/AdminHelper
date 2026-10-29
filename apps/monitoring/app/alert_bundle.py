# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bundled alert for agents that stop or resume reporting together
(docs/features/monitoring-alert-quality.md, "Sammelmeldung").

flush_agent_alerts collects the agent heartbeats not reported yet: BUNDLE_MIN or
more of one kind are claimed and bundled at once, fewer go out one by one once
they are BUNDLE_WINDOW old, or sooner when their next check is due before
(_alone_wait). send_bundle reports claimed heartbeats on each channel on its
own: an alert rule, or the bell per severity level, that would get BUNDLE_MIN or
more of them gets one message, below that each member gets the single message
process_alert would send. The scheduler runs flush_agent_alerts
every FLUSH_SECONDS as system:agent-alert-bundle; execute_check leaves a
heartbeat's notification to it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy.orm import Session

from app import alerter, check_engine
from app.core import database
from app.core.time import utcnow_naive
from app.maintenance import is_in_maintenance
from app.models import (
    MonitorCheck,
    MonitorMaintenance,
    MonitorState,
    MonitorTemplateAssignment,
)

logger = logging.getLogger("monitor.alert_bundle")

# From this many members on, a channel gets one message instead of single ones.
BUNDLE_MIN = 3
# Fewer heartbeats of a kind wait this long for more before each goes out alone,
# at most until a minute before the heartbeat's next check (_alone_wait).
BUNDLE_WINDOW = timedelta(minutes=5)
# The job's period: a heartbeat alone goes out at most this long after its wait.
FLUSH_SECONDS = 30
# Member lines in the message text; the webhook's members list carries them all.
MAX_TEXT_LINES = 50
# Most server ids the hub takes in one event (IncomingEvent.source_ids, server).
HUB_MAX_IDS = 500

# The two kinds of a bundle: heartbeats gone critical, heartbeats ok again.
SILENT = "silent"
BACK = "back"


class Entry(NamedTuple):
    """A claimed member: the check, its state row and the status last reported
    before the claim."""

    check: MonitorCheck
    state: MonitorState
    old_status: str | None


class _Kind(NamedTuple):
    old_status: str
    status: str
    icon: str
    # "<n> agents not reporting" in the subject and the text.
    wording: str
    # The bell's title and body are fixed: no server and no count. The hub adds
    # both per user, of the servers that user may see.
    bell_title: str
    bell_body: str


_KINDS = {
    SILENT: _Kind(
        "ok",
        "critical",
        "\U0001f534",
        "agents not reporting",
        "[AdminHelper Monitor] Agents not reporting",
        "The agents of these servers stopped reporting:",
    ),
    BACK: _Kind(
        "critical",
        "ok",
        "\u2705",
        "agents reporting again",
        "[AdminHelper Monitor] Agents reporting again",
        "The agents of these servers are reporting again:",
    ),
}

# The kind of an open heartbeat by its status. agent_ping knows only ok,
# critical and unknown, and unknown is never reported.
_KIND_OF_STATUS = {spec.status: kind for kind, spec in _KINDS.items()}


class _Open(NamedTuple):
    """A heartbeat not reported yet, as the selection of a run saw it."""

    check_id: str
    status: str
    notified_status: str | None
    since: datetime
    interval: str


def flush_agent_alerts(now: datetime | None = None) -> None:
    """The job system:agent-alert-bundle: report the agent heartbeats whose status
    differs from the one last reported ("Sammelmeldung", steps 1-4).

    The sent-state is the buffer: such a discrepancy stays open in
    monitor_states until it is reported, so every run starts afresh in a session
    of its own and a restart loses nothing. Per kind, BUNDLE_MIN or more open
    heartbeats are claimed and bundled, whatever their age; fewer wait until they
    are _alone_wait old and then go out one by one on the single path
    (dispatch_alert_bg, which claims each itself). A heartbeat muted by a
    maintenance window or a Host Ping does not count and stays open, as in
    process_alert, and once the muting is over only after its next evaluation
    (_awaits_check).

    The session is reached as ``database.SessionLocal``, the one patch point it
    shares with dispatch_alert_bg. Errors are logged and rolled back; a claim
    committed before them stands (at most once, as in process_alert)."""
    now = now if now is not None else utcnow_naive()
    db = database.SessionLocal()
    try:
        candidates = _candidates(db, now)
        # The selection only read: end its transaction, so none stays open across
        # the channel I/O below.
        db.rollback()
        for kind, found in candidates.items():
            if len(found) >= BUNDLE_MIN:
                entries = _claim(db, kind, [c.check_id for c in found])
                if entries:
                    send_bundle(db, kind, entries, now)
                    db.commit()
                continue
            for c in found:
                if c.since <= now - _alone_wait(c.interval):
                    check_engine.dispatch_alert_bg(c.check_id, c.notified_status, c.status)
    except Exception:
        db.rollback()
        logger.exception("Agent alert bundle failed")
    finally:
        db.close()


def _candidates(db: Session, now: datetime) -> dict[str, list[_Open]]:
    """The open heartbeats per kind (steps 1-2): enabled agent_ping checks whose
    status the alerter would report (resolve_notification "notify") and that are
    _reportable at now."""
    rows = (
        db.query(MonitorCheck, MonitorState)
        .join(MonitorState, MonitorState.check_id == MonitorCheck.id)
        .filter(
            MonitorCheck.check_type == "agent_ping",
            MonitorCheck.enabled == True,  # noqa: E712
            MonitorState.status.in_(list(_KIND_OF_STATUS)),
            MonitorState.status.is_distinct_from(MonitorState.notified_status),
        )
        .order_by(MonitorCheck.id)
        .all()
    )
    found: dict[str, list[_Open]] = {kind: [] for kind in _KINDS}
    for check, state in rows:
        if alerter.resolve_notification(state.notified_status, state.status) != "notify":
            continue
        if not _reportable(db, check, state, now):
            continue
        found[_KIND_OF_STATUS[state.status]].append(
            _Open(check.id, state.status, state.notified_status, state.since, check.interval)
        )
    return found


def _reportable(db: Session, check: MonitorCheck, state: MonitorState, now: datetime) -> bool:
    """Whether the heartbeat's open status may be reported at now: not muted
    (muted_reason, as in process_alert) and not one that awaits its next
    evaluation after a muting (_awaits_check)."""
    return alerter.muted_reason(db, check, now) is None and not _awaits_check(db, check, state)


def _awaits_check(db: Session, check: MonitorCheck, state: MonitorState) -> bool:
    """True while the status of a heartbeat not muted now may still be the one it
    was checked with under a muting that is over: its last evaluation fell into a
    maintenance window of its server, or a Host Ping of its server changed its
    status after it (T19, branch review). Reported from it, a host back after an
    outage, or an agent back at the end of a window, got a CRITICAL, and the
    all-clear only after the hold. The next evaluation decides instead: still
    silent, the heartbeat is reported; back, a problem never reported ends in
    silence, as anywhere else.

    A Host Ping's since is the time of its last change, back to ok after its hold
    when it muted the heartbeat. What it changed from is not stored, so any change
    after the heartbeat's last check holds it back, for one evaluation at most. A
    window deleted or disabled is not seen."""
    # last_check is empty only on a row no evaluation wrote. since is never later
    # than it, so counting from since holds back at least as much.
    checked = state.last_check or state.since
    windows = (
        db.query(MonitorMaintenance).filter(MonitorMaintenance.enabled == True).all()  # noqa: E712
    )
    if windows and is_in_maintenance(windows, check.server_id, checked):
        return True
    if not check.server_id:
        return False
    changed = (
        db.query(MonitorState.check_id)
        .join(MonitorCheck, MonitorCheck.id == MonitorState.check_id)
        .filter(
            MonitorCheck.server_id == check.server_id,
            MonitorCheck.check_type == "ping",
            MonitorCheck.template_def_id == alerter.HOST_PING_DEF_ID,
            MonitorCheck.enabled == True,  # noqa: E712
            MonitorState.since > checked,
        )
        .first()
    )
    return changed is not None


def _alone_wait(interval: str) -> timedelta:
    """How long a heartbeat of this interval waits for others before it goes out
    alone: BUNDLE_WINDOW, but at most until a minute before its next check, and
    never below zero (Kevin 2026-10-20). The next check may find the agent back,
    and a problem never reported then ends in silence: a heartbeat critical for
    one check of five minutes would never be reported. A string the scheduler
    does not take keeps BUNDLE_WINDOW."""
    # Function-local: the scheduler imports this module for the job.
    from app.scheduler import interval_timedelta

    period = interval_timedelta(interval)
    if period is None:
        return BUNDLE_WINDOW
    return max(min(BUNDLE_WINDOW, period - timedelta(minutes=1)), timedelta(0))


def _claim(db: Session, kind: str, check_ids: list[str]) -> list[Entry]:
    """Claim the open heartbeats of a bundle as process_alert claims one (step 4):
    lock the state rows in check_id order, re-read them and decide again, the
    muting and the evaluation after one included (_reportable); a heartbeat that
    moved on or got muted since the selection drops out and stays open. The rest
    is marked reported and committed before any channel I/O, so no row lock is
    held across it.

    The muting is decided at the time of the claim, not at the start of the run:
    a maintenance window started while the run sent the other kind (each rule up
    to its timeout) mutes this claim.

    Fewer than BUNDLE_MIN left claim nothing: they are as few as any other, and
    the next run lets them wait for the window instead of sending them early."""
    status = _KINDS[kind].status
    now = utcnow_naive()
    rows = (
        db.query(MonitorCheck, MonitorState)
        .join(MonitorState, MonitorState.check_id == MonitorCheck.id)
        .filter(MonitorState.check_id.in_(check_ids))
        # One lock order for every claim of several rows (4.46).
        .order_by(MonitorState.check_id)
        .with_for_update(of=MonitorState)
        # What the rows hold under the lock, not what this session read before.
        .populate_existing()
        .all()
    )
    entries = [
        Entry(check, state, state.notified_status)
        for check, state in rows
        if state.status == status
        and alerter.resolve_notification(state.notified_status, state.status) == "notify"
        and _reportable(db, check, state, now)
    ]
    if len(entries) < BUNDLE_MIN:
        db.rollback()
        return []
    for entry in entries:
        entry.state.notified_status = status
    db.commit()
    return entries


def send_bundle(db: Session, kind: str, entries: list[Entry], now: datetime) -> None:
    """Report claimed agent heartbeats of one kind (SILENT: now critical, BACK:
    ok again) on every channel.

    ``entries`` are (check, state, old_status) of members whose claim the caller
    has committed (notified_status set, as in process_alert); old_status is the
    status last reported before it. An alert rule's members are those it matches,
    when SILENT without those in its cooldown (a return passes the cooldown, as in
    process_alert); the bell's are those hub_decision lets through, split by the
    level they reach the bell with. A rule or a level with BUNDLE_MIN or more
    members gets one message and the rules an alert-log row per member; below that
    each member goes out on its own. The bell's record
    (hub_status, hub_sent_at) follows each event the hub accepted. Log rows and
    records are flushed; the caller commits them."""
    spec = _KINDS[kind]
    members = [Entry(check, state, alerter.reported_status(old)) for check, state, old in entries]
    names = _server_names(db, members)
    singles: dict[str, dict] = {}

    def single(entry: Entry) -> dict:
        # Built once per member and shared by the rules and the bell, as in
        # process_alert.
        if entry.check.id not in singles:
            singles[entry.check.id] = alerter.build_message(
                db, entry.check, entry.old_status, spec.status
            )
        return singles[entry.check.id]

    _send_rules(db, spec, members, names, single, now)
    _send_bell(spec, members, single, now)
    db.flush()


def _server_names(db: Session, members: list[Entry]) -> dict[str, str]:
    """server_id -> server_name of a template assignment of that server."""
    ids = {m.check.server_id for m in members if m.check.server_id}
    if not ids:
        return {}
    rows = (
        db.query(MonitorTemplateAssignment.server_id, MonitorTemplateAssignment.server_name)
        .filter(MonitorTemplateAssignment.server_id.in_(ids))
        .order_by(MonitorTemplateAssignment.id)
        .all()
    )
    names: dict[str, str] = {}
    for server_id, name in rows:
        if name:
            names.setdefault(server_id, name)
    return names


def _send_rules(
    db: Session,
    kind: _Kind,
    members: list[Entry],
    names: dict[str, str],
    single: Callable[[Entry], dict],
    now: datetime,
) -> None:
    is_recovery = kind.status == "ok"
    for rule in alerter.enabled_rules(db):
        matched = [
            m for m in members if alerter.rule_applies(db, rule, m.check, is_recovery=is_recovery)
        ]
        # The messages are built before the rule's first send.
        if len(matched) >= BUNDLE_MIN:
            sends = [(matched, _bundle_message(kind, matched, names))]
        else:
            sends = [([m], single(m)) for m in matched]
        for group, msg in sends:
            alerter.send_to_rule(
                db, rule, [(m.check, m.old_status) for m in group], msg, kind.status, now
            )


def _bundle_message(kind: _Kind, members: list[Entry], names: dict[str, str]) -> dict:
    """The message of a bundle in the shape of build_message, plus ``members``.
    The label is capped like a single subject, at the highest severity of the
    members; the text keeps the real status."""
    is_recovery = kind.status == "ok"
    severity = alerter.highest_severity(m.check.severity for m in members)
    if is_recovery:
        label = head = "RECOVERY"
    else:
        label = alerter.capped_label(kind.status, severity)
        head = kind.status.upper()
    count = f"{len(members)} {kind.wording}"
    lines = [_line(m, names) for m in members[:MAX_TEXT_LINES]]
    if len(members) > MAX_TEXT_LINES:
        lines.append(f"\u2026 and {len(members) - MAX_TEXT_LINES} more")
    return {
        # A bundle has no single check or server; ``members`` names them.
        "check_name": None,
        "check_type": members[0].check.check_type,
        "server_id": None,
        "severity": severity,
        "old_status": kind.old_status,
        "new_status": kind.status,
        "is_recovery": is_recovery,
        "icon": kind.icon,
        "subject": f"[AdminHelper Monitor] {label}: {count}",
        "text": "\n".join([head, f"{count}:", *lines]),
        "members": [
            {
                "check_id": m.check.id,
                "check_name": m.check.name,
                "server_id": m.check.server_id,
                "server_name": names.get(m.check.server_id),
                "old_status": m.old_status,
                "new_status": kind.status,
                "message": m.state.message,
            }
            for m in members
        ],
    }


def _line(entry: Entry, names: dict[str, str]) -> str:
    server = names.get(entry.check.server_id) or entry.check.server_id or entry.check.name
    message = entry.state.message
    return f"- {server}: {message}" if message else f"- {server}"


def _send_bell(
    kind: _Kind, members: list[Entry], single: Callable[[Entry], dict], now: datetime
) -> None:
    """Every event is built before the first POST and the bell's record is set
    after the last: no database access between the POSTs, so no write of this
    session holds a row across hub I/O (process_alert's claim-then-dispatch, 5.3)."""
    emit = [
        m
        for m in members
        if alerter.hub_decision(
            m.state.hub_status, m.state.hub_sent_at, kind.status, m.check.severity, now
        )
        == "emit"
    ]
    # One event per level (Kevin 2026-10-20): alert.triggered then reaches only
    # servers whose own check is critical, and min_severity applies per server.
    levels: dict[str, list[Entry]] = {}
    for m in emit:
        severity = alerter.bell_severity(
            m.state.hub_status, m.old_status, kind.status, m.check.severity
        )
        levels.setdefault(severity, []).append(m)
    singles: list[tuple[Entry, dict, str]] = []
    bundles: list[tuple[list[Entry], dict]] = []
    for severity, group in levels.items():
        # The hub routes a bundle by server; a heartbeat without one goes out on
        # its own, to the admins as before.
        bundled = [m for m in group if m.check.server_id]
        if len(bundled) < BUNDLE_MIN:
            bundled = []
        in_bundle = {m.check.id for m in bundled}
        singles += [(m, single(m), severity) for m in group if m.check.id not in in_bundle]
        server_ids = list(dict.fromkeys(m.check.server_id for m in bundled))
        for start in range(0, len(server_ids), HUB_MAX_IDS):
            chunk_ids = server_ids[start : start + HUB_MAX_IDS]
            wanted = set(chunk_ids)
            chunk = [m for m in bundled if m.check.server_id in wanted]
            bundles.append((chunk, _bundle_payload(kind, severity, chunk_ids)))

    accepted: list[Entry] = []
    for m, msg, severity in singles:
        if alerter.emit_to_hub(m.check, m.old_status, kind.status, msg, severity=severity):
            accepted.append(m)
    for chunk, payload in bundles:
        if alerter.post_hub_event(payload, "agent bundle"):
            accepted += chunk
    # What the bell now shows of each member, as process_alert records it.
    for m in accepted:
        m.state.hub_status, m.state.hub_sent_at = alerter.bell_record(
            kind.status, m.check.severity, m.state.hub_sent_at, now
        )


def _bundle_payload(kind: _Kind, severity: str, server_ids: list[str]) -> dict:
    return {
        "event_type": "monitoring.check.transition",
        "severity": severity,
        "category": "monitoring",
        "title": kind.bell_title,
        "body": kind.bell_body,
        "source_type": "server",
        "source_ids": server_ids,
        "new_status": kind.status,
    }
