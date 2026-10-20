# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bundled alert for agents that stop or resume reporting together
(docs/features/monitoring-alert-quality.md, "Sammelmeldung").

send_bundle reports agent heartbeats the caller has already claimed, on each
channel on its own: an alert rule, or the bell per severity level, that would get
BUNDLE_MIN or more of them gets one message, below that each member gets the
single message process_alert would send. Not wired up yet.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import NamedTuple

from sqlalchemy.orm import Session

from app import alerter
from app.models import (
    MonitorAlertLog,
    MonitorAlertRule,
    MonitorCheck,
    MonitorState,
    MonitorTemplateAssignment,
)

logger = logging.getLogger("monitor.alert_bundle")

# From this many members on, a channel gets one message instead of single ones.
BUNDLE_MIN = 3
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
    members = [Entry(check, state, _reported(old)) for check, state, old in entries]
    names = _server_names(db, members)
    singles: dict[str, dict] = {}

    def single(entry: Entry) -> dict:
        # Built once per member and shared by the rules and the bell, as in
        # process_alert.
        if entry.check.id not in singles:
            singles[entry.check.id] = alerter._build_message(
                db, entry.check, entry.old_status, spec.status
            )
        return singles[entry.check.id]

    _send_rules(db, spec, members, names, single, now)
    _send_bell(spec, members, single, now)
    db.flush()


def _reported(old_status: str | None) -> str:
    # As process_alert: nothing reported before (None, pending; unknown only via
    # the migration backfill) reads as ok.
    return old_status if old_status not in (None, "pending", "unknown") else "ok"


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
    rules = db.query(MonitorAlertRule).filter(MonitorAlertRule.enabled == True).all()  # noqa: E712
    for rule in rules:
        matched = [
            m
            for m in members
            if alerter._rule_matches(rule, m.check)
            and (is_recovery or not alerter._is_in_cooldown(db, rule, m.check))
        ]
        # The messages are built before the rule's first send.
        if len(matched) >= BUNDLE_MIN:
            sends = [(matched, _bundle_message(kind, matched, names))]
        else:
            sends = [([m], single(m)) for m in matched]
        for group, msg in sends:
            # The first member stands in as the check the channel names in its
            # service log; _send_webhook and _send_email stay as they are.
            success, error = _dispatch_isolated(rule, group[0].check, msg)
            # One row per member, so the rule's cooldown per check holds.
            for m in group:
                db.add(
                    MonitorAlertLog(
                        alert_rule_id=rule.id,
                        check_id=m.check.id,
                        old_status=m.old_status,
                        new_status=kind.status,
                        sent_at=now,
                        success=success,
                        error=error,
                    )
                )


def _dispatch_isolated(
    rule: MonitorAlertRule, check: MonitorCheck, msg: dict
) -> tuple[bool, str | None]:
    # Isolated as in process_alert: a misconfigured rule must not stop the others.
    try:
        return alerter._dispatch(rule, check, msg)
    except Exception as exc:
        logger.exception("Bundled alert dispatch failed for rule %s", rule.id)
        return False, f"Dispatch failed ({type(exc).__name__})"


def _bundle_message(kind: _Kind, members: list[Entry], names: dict[str, str]) -> dict:
    """The message of a bundle in the shape of _build_message, plus ``members``.
    The label is capped like a single subject, at the highest severity of the
    members; the text keeps the real status."""
    is_recovery = kind.status == "ok"
    level = max(alerter._severity_level(m.check.severity) for m in members)
    if is_recovery:
        label = head = "RECOVERY"
    else:
        label = alerter._LEVEL_SEVERITY[min(alerter._STATUS_LEVEL[kind.status], level)].upper()
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
        "severity": alerter._LEVEL_SEVERITY[level],
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
        levels.setdefault(_bell_severity(kind, m), []).append(m)
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
        if alerter._emit_to_hub(m.check, m.old_status, kind.status, msg, severity=severity):
            accepted.append(m)
    for chunk, payload in bundles:
        if alerter._post_hub_event(payload, "agent bundle"):
            accepted += chunk
    for m in accepted:
        _record_bell(m, kind.status, now)


def _bell_severity(kind: _Kind, entry: Entry) -> str:
    """The level the member reaches the bell with, as in process_alert: capped at
    the check's severity, a recovery at the level its alarm reached the bell with."""
    if kind.status == "ok":
        return entry.state.hub_status
    return alerter._hub_severity(entry.old_status, kind.status, entry.check.severity)


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


def _record_bell(entry: Entry, status: str, now: datetime) -> None:
    """What the bell now shows of the member, as process_alert records it: a
    problem starts the cooldown, a recovery leaves hub_sent_at as it was."""
    entry.state.hub_status = alerter._capped_status(status, entry.check.severity)
    if status != "ok":
        entry.state.hub_sent_at = now
