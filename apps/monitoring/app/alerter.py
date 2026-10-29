# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Alerter — webhook + email dispatch for monitoring alerts.

Called from both BG dispatch paths whenever a check evaluation diverges from
the last reported status (sent-state, docs/features/alert-sent-state.md).
Evaluates alert rules, cooldown and sends out notifications.
"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import NamedTuple
from urllib.parse import urlparse

import httpx
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.config import (
    INTERNAL_API_KEY,
    SERVER_HUB_URL,
    SMTP_CA_FILE,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
)
from app.core.ssrf import UrlVerdict, check_target, pinned_client
from app.core.time import utcnow_naive
from app.maintenance import is_in_maintenance
from app.models import (
    MonitorAlertLog,
    MonitorAlertRule,
    MonitorCheck,
    MonitorMaintenance,
    MonitorState,
)

logger = logging.getLogger("monitor.alerter")

# Hub severity of a transition = the worse of the two states (info<warning<
# critical), capped at the check's severity. A recovery (warning->ok) therefore
# keeps the "warning" level so it still reaches subscribers with a warning
# threshold; an escalation (ok->critical) is "critical", for a check with
# severity warning "warning". unknown is treated as warning-level. ok and
# pending are level 0 ("nothing wrong"), so a check first coming up clean
# (pending->ok) and every transition of an info check are NOT pushed (see
# emit_to_hub). The same table caps the label in the message subject.
_STATUS_LEVEL = {"ok": 0, "info": 0, "pending": 0, "unknown": 1, "warning": 1, "critical": 2}
_LEVEL_SEVERITY = {0: "info", 1: "warning", 2: "critical"}
_SEVERITY_LEVEL = {"info": 0, "warning": 1, "critical": 2}

# Bell cooldown (docs/features/monitoring-alert-quality.md): at most one problem
# per check in this window reaches the notification hub; see hub_decision.
HUB_COOLDOWN = timedelta(minutes=30)

# The longest title the hub takes: IncomingEvent.title in the server
# (apps/server/app/modules/notifications/schemas.py). A longer one turns the push
# into a 422, and the bell gets nothing; test_alerter_hub keeps both equal.
HUB_TITLE_MAX = 512

# In the subject, every control character of the check name (Unicode category Cc: C0, DEL,
# C1) and the line and paragraph separators become a space, one for one. The subject is a
# mail header value, and Python's email package refuses to write a header that spans more
# than one line, so the mail would not go out. Text and check_name keep the name as it is.
_SUBJECT_TO_SPACE = str.maketrans(
    dict.fromkeys([*range(0x20), *range(0x7F, 0xA0), 0x2028, 0x2029], " ")
)


def resolve_notification(notified_status: str | None, new_status: str) -> str:
    """Sent-state decision (docs/features/alert-sent-state.md): compare the
    status the alerter last actually reported with the current evaluation.

    Returns:
        "notify"     — report the discrepancy (alert or recovery).
        "silent_ack" — record new_status as reported WITHOUT notifying: an ok
                       that never had a reported problem (first evaluation,
                       unknown flapping) must not dispatch a recovery.
        "skip"       — nothing to report; notified_status stays untouched so a
                       suppressed discrepancy survives for later catch-up.
    """
    if new_status == notified_status:
        return "skip"
    # unknown never notifies (unknown policy) and never counts as reported —
    # the pre-unknown discrepancy stays pending.
    if new_status == "unknown":
        return "skip"
    if new_status == "ok" and notified_status not in ("warning", "critical"):
        return "silent_ack"
    return "notify"


def enabled_rules(db: Session) -> list[MonitorAlertRule]:
    return db.query(MonitorAlertRule).filter(MonitorAlertRule.enabled == True).all()  # noqa: E712


def reported_status(notified: str | None) -> str:
    """The receiver-facing "old" status: the last REPORTED one. None/pending/unknown
    mean "nothing was ever reported" (unknown only via the migration backfill) and
    read as ok."""
    return notified if notified not in (None, "pending", "unknown") else "ok"


def rule_applies(
    db: Session, rule: MonitorAlertRule, check: MonitorCheck, *, is_recovery: bool
) -> bool:
    if not _rule_matches(rule, check):
        return False
    # Never block recovery alerts via cooldown
    if not is_recovery and _is_in_cooldown(db, rule, check):
        logger.debug("Alert-Rule %s fuer Check %s im Cooldown", rule.id, check.id)
        return False
    return True


def send_to_rule(
    db: Session,
    rule: MonitorAlertRule,
    members: Sequence[tuple[MonitorCheck, str]],
    msg: dict,
    new_status: str,
    sent_at: datetime | None = None,
) -> None:
    """Sends one message over the rule's channel and adds an alert-log row per
    member (check, reported old status), so the rule's cooldown per check holds.
    The first member stands in as the check the channel names in its service log.
    Without ``sent_at`` the rows carry the time after the send."""
    try:
        success, error = _dispatch(rule, members[0][0], msg)
    except Exception as exc:
        # Isolate each rule's dispatch: a misconfigured rule (e.g. smtp_port "abc" or
        # non-string recipients, which parse in _send_email BEFORE its own try) would
        # otherwise abort the whole loop — no db.flush(), and execute_check rolls back every
        # other rule's already-created alert log, silently suppressing all their alerts (4.45).
        logger.exception("Alert dispatch failed for rule %s", rule.id)
        success, error = False, f"Dispatch failed ({type(exc).__name__})"
    stamp = sent_at if sent_at is not None else utcnow_naive()
    for check, old_status in members:
        db.add(
            MonitorAlertLog(
                alert_rule_id=rule.id,
                check_id=check.id,
                old_status=old_status,
                new_status=new_status,
                sent_at=stamp,
                success=success,
                error=error,
            )
        )


def process_alert(
    db: Session,
    check: MonitorCheck,
    old_status: str,
    new_status: str,
) -> None:
    """Evaluates all alert rules and sends out matching notifications.

    Sent-state semantics (docs/features/alert-sent-state.md): the decision is
    driven by MonitorState.notified_status — the status last actually reported
    — not by the raw transition. Suppressed discrepancies (maintenance,
    host-down) leave notified_status untouched, so a later evaluation catches
    them up once the suppression is gone. ``old_status`` is the caller's
    transition context; it only serves as the notified fallback when no state
    row exists. ``new_status`` is likewise only a snapshot — the CURRENT
    state.status re-read under the lock is authoritative.

    Claim-then-dispatch: the claim (notified_status = current) is committed by
    THIS function BEFORE any channel I/O, so the row lock never spans
    webhook/SMTP timeouts and a later commit failure cannot re-fire an
    already-sent alert (at-most-once). The alert-log rows written afterwards
    are only flushed — the caller's commit persists them. The claim also
    reserves the bell's slot (hub_status, hub_sent_at); handing it back after a
    failed hub POST likewise comes with the caller's commit.
    """
    claim = _claim_transition(db, check, old_status, new_status)
    if claim is None:
        return

    # Build the alert message once per transition on the caller's session, then
    # reuse it for every rule dispatch and the hub emit — avoids N+1 sessions and
    # a text that could diverge if the state row changed between builds (2.30).
    msg = build_message(db, check, claim.reported_old, claim.new_status)

    is_recovery = claim.new_status == "ok"
    for rule in claim.rules:
        if rule_applies(db, rule, check, is_recovery=is_recovery):
            send_to_rule(db, rule, [(check, claim.reported_old)], msg, claim.new_status)

    # The claim was committed before the I/O above; only the alert-log rows
    # remain for the caller's commit.
    db.flush()

    _notify_bell(db, check, claim, msg)


class _Claim(NamedTuple):
    """What _claim_transition committed: the transition to report and the bell's
    slot before and after the reservation."""

    state: MonitorState | None
    rules: list[MonitorAlertRule]
    reported_old: str
    new_status: str
    hub_emit: bool
    hub_before: tuple[str | None, datetime | None]
    hub_reserved: tuple[str | None, datetime | None]


def _claim_transition(
    db: Session, check: MonitorCheck, old_status: str, new_status: str
) -> _Claim | None:
    """The claim phase of process_alert — a short FOR UPDATE window with no I/O
    inside, committed before any channel I/O. None when nothing is to be sent."""
    # The lock serializes concurrent BG dispatches for the same check: the second
    # one re-reads the already-claimed notified_status and skips (no-op on sqlite).
    state = (
        db.query(MonitorState).filter(MonitorState.check_id == check.id).with_for_update().first()
    )
    # Re-read the CURRENT status under the lock: the caller's new_status may be
    # stale when dispatches run out of submission order — dispatching the
    # snapshot would report a phantom transition and move notified backwards.
    current = state.status if state is not None else new_status
    notified = state.notified_status if state is not None else old_status
    decision = resolve_notification(notified, current)
    if decision == "skip":
        # Nothing new to report (incl. every transition INTO 'unknown' — the
        # unknown policy; a pre-unknown discrepancy stays pending for catch-up).
        return None
    if decision == "silent_ack":
        # An ok that never had a reported problem (first evaluation, unknown
        # flapping): record it as reported WITHOUT dispatching a recovery.
        if state is not None:
            state.notified_status = current
            db.flush()
        return None

    # Maintenance windows and host-down (muted_reason): the state transition has
    # already been persisted by the caller — only notifications are muted, and
    # notified_status stays untouched for the catch-up. No alert-log entry
    # either: the log records SENT notifications.
    reason = muted_reason(db, check, utcnow_naive())
    if reason is not None:
        logger.debug("Alert for check %s suppressed (%s)", check.id, reason)
        return None

    rules = enabled_rules(db)
    hub_emit, hub_before, hub_reserved = _reserve_bell(state, check, notified, current)

    # Claim BEFORE the channel I/O and commit it: the row lock is released, so
    # scheduler workers and push threads never wait on webhook/SMTP timeouts
    # (the 5.3 isolation stays intact), and a commit failure after the send can
    # no longer re-fire an already-sent alert — at-most-once by design
    # ("reported" = the claim persisted).
    if state is not None:
        state.notified_status = current
        if hub_emit:
            state.hub_status, state.hub_sent_at = hub_reserved
        db.commit()
    # The receiver-facing "old" is the last REPORTED status, not the raw
    # transition: a catch-up after host-down reads ok -> critical, a
    # post-maintenance recovery critical -> ok.
    return _Claim(
        state, rules, reported_status(notified), current, hub_emit, hub_before, hub_reserved
    )


def _reserve_bell(
    state: MonitorState | None, check: MonitorCheck, notified: str | None, new_status: str
) -> tuple[bool, tuple[str | None, datetime | None], tuple[str | None, datetime | None]]:
    """(emit, slot before, slot reserved) of the bell for this transition.

    The bell (notification hub) has its own cooldown (hub_decision). It decides
    under the claim's lock and its slot is reserved with the claim, so a dispatch
    of this check that starts while this one is still in its hub POST reads what
    this one is about to show, not the record from before. What the bell skips is
    dropped: the claim records the transition as reported, nothing is caught up.
    Without a state row (the notified fallback) the bell is taken to have shown
    what the rules reported, and nothing is recorded."""
    now = utcnow_naive()
    if state is not None:
        before = (state.hub_status, state.hub_sent_at)
    else:
        before = (_capped_status(notified, check.severity), None)
    emit = hub_decision(*before, new_status, check.severity, now) == "emit"
    return emit, before, bell_record(new_status, check.severity, before[1], now)


def _notify_bell(db: Session, check: MonitorCheck, claim: _Claim, msg: dict) -> None:
    """Independently of the rule-based webhook/email dispatch, push the transition
    to the server's notification hub for per-user routing; a failed POST hands the
    reserved slot back."""
    if not claim.hub_emit:
        return
    severity = bell_severity(
        claim.hub_before[0], claim.reported_old, claim.new_status, check.severity
    )
    if emit_to_hub(check, claim.reported_old, claim.new_status, msg, severity=severity):
        return
    if claim.state is not None:
        _release_hub_slot(db, check.id, claim.hub_reserved, claim.hub_before)


def _release_hub_slot(
    db: Session,
    check_id: str,
    reserved: tuple[str | None, datetime | None],
    before: tuple[str | None, datetime | None],
) -> None:
    """Give back the bell slot of a hub POST that failed — only while the row
    still carries this reservation: a dispatch that reserved after this one keeps
    its own. Comes with the caller's commit, like the alert-log rows."""
    db.query(MonitorState).filter(
        MonitorState.check_id == check_id,
        MonitorState.hub_status == reserved[0],
        MonitorState.hub_sent_at.is_not_distinct_from(reserved[1]),
    ).update({"hub_status": before[0], "hub_sent_at": before[1]}, synchronize_session=False)


def muted_reason(db: Session, check: MonitorCheck, now: datetime) -> str | None:
    """Why the notifications of the check are muted at ``now``; None when they
    are not.

    "maintenance window" — a window of the check's server or of all servers is
    active (collect-but-mute, T25); it mutes every check, the heartbeat and the
    Host Ping included.
    "host down" — the server's heartbeat or Host Ping stands critical
    (_host_is_down): one incident, one notification."""
    windows = (
        db.query(MonitorMaintenance).filter(MonitorMaintenance.enabled == True).all()  # noqa: E712
    )
    if windows and is_in_maintenance(windows, check.server_id, now):
        return "maintenance window"
    if _host_is_down(db, check):
        return "host down"
    return None


# def_id of the check in the built-in template "Host Ping" (builtin_templates.py).
# Only its ping signals host-down: a ping set up by hand may aim at another target
# (a gateway, say) and must not mute the whole server.
HOST_PING_DEF_ID = "host-ping"


def _host_is_down(db: Session, check: MonitorCheck) -> bool:
    """True when an enabled check of the same server that signals host-down
    stands critical (Alertmanager inhibition pattern), by rank:

    - the Host Ping (ping check with template_def_id HOST_PING_DEF_ID): never;
    - agent_ping: a Host Ping;
    - every other check: an agent_ping or a Host Ping.

    So a critical heartbeat never mutes the Host Ping, and the two do not
    silence each other when the host is gone. No check mutes itself; checks
    without a server are never muted.

    ANY-semantics on purpose: with several signal checks per server (manual
    plus template is possible — no unique constraint), picking an arbitrary row
    would make suppression depend on row order; filtering on critical makes it
    deterministic."""
    if not check.server_id:
        return False
    if check.check_type == "ping" and check.template_def_id == HOST_PING_DEF_ID:
        return False
    host_ping = and_(
        MonitorCheck.check_type == "ping", MonitorCheck.template_def_id == HOST_PING_DEF_ID
    )
    if check.check_type == "agent_ping":
        signal = host_ping
    else:
        signal = or_(MonitorCheck.check_type == "agent_ping", host_ping)
    row = (
        db.query(MonitorState.status)
        .join(MonitorCheck, MonitorCheck.id == MonitorState.check_id)
        .filter(
            MonitorCheck.server_id == check.server_id,
            signal,
            MonitorCheck.enabled == True,  # noqa: E712
            MonitorState.status == "critical",
        )
        .first()
    )
    return row is not None


def _severity_level(severity: str) -> int:
    """Level of a check's severity. A value outside VALID_SEVERITIES (the routers
    reject it) caps nothing rather than silence an alert."""
    return _SEVERITY_LEVEL.get(severity, 2)


def _hub_severity(old_status: str, new_status: str, severity: str) -> str:
    """Severity of a transition for the hub = the worse of the two states, at most
    the check's severity."""
    level = max(_STATUS_LEVEL.get(old_status, 1), _STATUS_LEVEL.get(new_status, 1))
    return _LEVEL_SEVERITY[min(level, _severity_level(severity))]


def highest_severity(severities: Iterable[str]) -> str:
    return _LEVEL_SEVERITY[max(_severity_level(s) for s in severities)]


def capped_label(status: str, severity: str) -> str:
    """The label of a message subject: the status at most at the severity."""
    return _LEVEL_SEVERITY[min(_STATUS_LEVEL.get(status, 1), _severity_level(severity))].upper()


def bell_severity(hub_status: str | None, old_status: str, new_status: str, severity: str) -> str:
    """The level a transition reaches the bell with: capped at the check's severity
    (_hub_severity). A recovery reaches it at the level its alarm reached it with
    (``hub_status``), not at the check's severity as it is now: lowered in between,
    a subscriber with min_severity critical would see the alarm but never the
    all-clear."""
    if new_status == "ok":
        return hub_status
    return _hub_severity(old_status, new_status, severity)


def bell_record(
    status: str, severity: str, sent_at: datetime | None, now: datetime
) -> tuple[str | None, datetime | None]:
    """(hub_status, hub_sent_at) once the bell showed ``status``: a problem starts
    the cooldown, a recovery leaves hub_sent_at as it was."""
    return _capped_status(status, severity), sent_at if status == "ok" else now


def _capped_status(status: str | None, severity: str) -> str | None:
    """What hub_status records of a status: a problem at most at the check's
    severity, the level its event reached the bell with (warning/critical, info
    for a check with severity info); any other status as it is."""
    if status in ("warning", "critical"):
        return _LEVEL_SEVERITY[min(_STATUS_LEVEL[status], _severity_level(severity))]
    return status


def hub_decision(
    hub_status: str | None,
    hub_sent_at: datetime | None,
    new_status: str,
    severity: str,
    now: datetime,
) -> str:
    """Bell decision for a transition the alerter reports
    (docs/features/monitoring-alert-quality.md, "Glocken-Cooldown").

    ``hub_status`` is what the bell last showed of the check (_capped_status),
    ``hub_sent_at`` when it last got a problem of it.

    Returns:
        "emit" — a recovery of a problem the bell showed; a shown warning that
                 escalates to critical (capped at the severity); any other
                 problem when no problem went to the bell in HUB_COOLDOWN.
        "skip" — a recovery of a problem the bell never showed; a problem at
                 capped level info; any other problem inside the cooldown.
    """
    if new_status == "ok":
        # The bell clears only what it showed, at the level it showed it.
        return "emit" if hub_status in ("warning", "critical") else "skip"
    level = min(_STATUS_LEVEL.get(new_status, 1), _severity_level(severity))
    if level == 0:
        return "skip"
    if hub_status == "warning" and level == 2:
        return "emit"
    if hub_sent_at is not None and now - hub_sent_at < HUB_COOLDOWN:
        return "skip"
    return "emit"


def emit_to_hub(
    check: MonitorCheck,
    old_status: str,
    new_status: str,
    msg: dict,
    severity: str | None = None,
) -> bool:
    """Push the status transition to the server's notification hub (best-effort).

    The server owns the user<->server mapping and decides who gets notified;
    monitoring stays a pure event source. A failed push must never break the
    alert path, so errors are logged, not raised. ``severity`` replaces the one
    computed from the transition (process_alert: a recovery at the level of its
    alarm). Returns whether the hub accepted the event."""
    if severity is None:
        severity = _hub_severity(old_status, new_status, check.severity)
    # An info-level transition only involves ok/pending — not notification-worthy
    # (e.g. a check first coming up clean, or flapping at the bottom) — or belongs
    # to a check with severity info. Skip it so it never spams the hub; real
    # recoveries (warning/critical -> ok) keep their severity and are pushed.
    if severity == "info":
        return False
    # The check name has no length limit; mail and webhook keep the full subject.
    title = msg["subject"]
    if len(title) > HUB_TITLE_MAX:
        title = title[: HUB_TITLE_MAX - 1] + "\u2026"
    payload = {
        "event_type": "monitoring.check.transition",
        "severity": severity,
        "category": "monitoring",
        "title": title,
        "body": msg["text"],
        "source_type": "server",
        "source_id": check.server_id,
        # severity is worse-of-both so recoveries reach warning-level
        # subscribers, capped at the check's severity so a warning check
        # never fires the critical-only alert.triggered hook; new_status lets
        # the server distinguish a real alert from a recovery (the hook must
        # not fire on the critical -> ok leg).
        "new_status": new_status,
    }
    return post_hub_event(payload, check.name)


def post_hub_event(payload: dict, label: str) -> bool:
    """POST one event to the server's notification hub; True when the hub
    accepted it. Never raises: errors are logged under ``label``."""
    if not SERVER_HUB_URL or not INTERNAL_API_KEY:
        return False
    try:
        resp = httpx.post(
            f"{SERVER_HUB_URL}/api/internal/events",
            json=payload,
            headers={"X-Internal-Key": INTERNAL_API_KEY},
            timeout=5,
            follow_redirects=False,
        )
        # httpx does not raise on 4xx/5xx — a rejected push (e.g. 403 from a
        # MONITOR_API_KEY mismatch) would otherwise be silently lost.
        if resp.status_code >= 300:
            logger.warning("Hub-Emit abgelehnt (%s): HTTP %s", label, resp.status_code)
            return False
    except Exception as exc:
        logger.warning("Hub-Emit fehlgeschlagen (%s): %s", label, exc)
        return False
    return True


def _rule_matches(rule: MonitorAlertRule, check: MonitorCheck) -> bool:
    """Checks whether an alert rule matches the check."""
    if rule.match_severity and rule.match_severity != check.severity:
        return False
    if rule.match_server_id and rule.match_server_id != check.server_id:
        return False
    return True


def _is_in_cooldown(db: Session, rule: MonitorAlertRule, check: MonitorCheck) -> bool:
    """Checks whether cooldown is still active for this rule+check combination."""
    # NULL is the default 30 of the schema, the template sync and the column: the
    # column is nullable, and PUT /alerts/{id} stores an explicit null.
    minutes = 30 if rule.cooldown_minutes is None else rule.cooldown_minutes
    try:
        cutoff = utcnow_naive() - timedelta(minutes=minutes)
    except OverflowError:
        # The schema allows up to int32 minutes, about 4000 years: a window that
        # reaches back before year 1 counts every earlier successful send.
        cutoff = datetime.min
    recent = (
        db.query(MonitorAlertLog)
        .filter(
            MonitorAlertLog.alert_rule_id == rule.id,
            MonitorAlertLog.check_id == check.id,
            MonitorAlertLog.sent_at >= cutoff,
            MonitorAlertLog.success == True,  # noqa: E712
        )
        .first()
    )
    return recent is not None


def _dispatch(
    rule: MonitorAlertRule,
    check: MonitorCheck,
    msg: dict,
) -> tuple[bool, str | None]:
    """Sends the notification over the configured channel."""
    try:
        config = json.loads(rule.channel_config) if rule.channel_config else {}
    except (json.JSONDecodeError, TypeError):
        return False, "Invalid channel_config"

    if rule.channel == "webhook":
        return _send_webhook(config, rule, check, msg)
    elif rule.channel == "email":
        return _send_email(config, rule, check, msg)
    else:
        return False, f"Unknown channel: {rule.channel}"


def build_message(db: Session, check: MonitorCheck, old_status: str, new_status: str) -> dict:
    """Builds the alert message as a dict. Uses the caller's session (built once
    per transition in process_alert), so it must not open its own (2.30)."""
    status_icons = {
        "ok": "\u2705",
        "warning": "\u26a0\ufe0f",
        "critical": "\U0001f534",
        "unknown": "\u2753",
    }
    is_recovery = new_status == "ok"
    subject_name = check.name.translate(_SUBJECT_TO_SPACE)

    if is_recovery:
        subject = f"[AdminHelper Monitor] RECOVERY: {subject_name}"
        text = (
            f"RECOVERY\n"
            f"Check: {check.name} ({check.check_type})\n"
            f"Status: {old_status} \u2192 OK\n"
            f"The check is OK again."
        )
    else:
        label = "CRITICAL" if new_status == "critical" else new_status.upper()
        # The subject (and with it the bell title) is capped at the check's
        # severity; the text keeps the real status.
        subject = (
            f"[AdminHelper Monitor] {capped_label(new_status, check.severity)}: {subject_name}"
        )
        text = (
            f"{label}\n"
            f"Check: {check.name} ({check.check_type})\n"
            f"Status: {old_status} \u2192 {new_status}\n"
            f"Severity: {check.severity}"
        )

    # Append check-state message (e.g. "Port 22: Connection refused")
    try:
        state = db.query(MonitorState).filter(MonitorState.check_id == check.id).first()
        if state and state.message:
            text += f"\nDetails: {state.message}"
    except Exception:
        logger.warning(
            "State-Message fuer Check '%s' konnte nicht geladen werden", check.name, exc_info=True
        )

    return {
        "check_name": check.name,
        "check_type": check.check_type,
        "server_id": check.server_id,
        "severity": check.severity,
        "old_status": old_status,
        "new_status": new_status,
        "is_recovery": is_recovery,
        "icon": status_icons.get(new_status, ""),
        "subject": subject,
        "text": text,
    }


def _log_host(url: str) -> str:
    """The host of a webhook URL for the service log. Many webhook services carry
    the credential in the path or the query, so nothing else of the URL is logged."""
    try:
        return urlparse(url).hostname or "?"
    except ValueError:
        # urlparse raises on a malformed IPv6 literal ("http://[::1").
        return "?"


def _webhook_failure(exc: Exception) -> str:
    """The alert-log reason for a failed webhook request: a fixed text per kind of
    error. The exception text goes to the service log only."""
    if isinstance(exc, httpx.TimeoutException):
        return "Webhook request timed out"
    if isinstance(exc, httpx.ConnectError):
        return "Webhook connection failed"
    return f"Webhook request failed ({type(exc).__name__})"


def _send_webhook(
    config: dict,
    rule: MonitorAlertRule,
    check: MonitorCheck,
    msg: dict,
) -> tuple[bool, str | None]:
    """Sends the alert to a webhook URL."""
    url = config.get("url")
    if not url:
        return False, "No webhook URL configured"

    # SSRF guard: a webhook URL is user-supplied; reject private/reserved
    # targets so it cannot probe the internal network from the monitor service
    # (same protection the HTTP checker already applies to its targets).
    target = check_target(url)
    if target.verdict is UrlVerdict.UNRESOLVED:
        logger.warning(
            "Webhook target rejected (could not be resolved): %s -> %s",
            check.name,
            _log_host(url),
        )
        return (
            False,
            "Webhook target could not be resolved (DNS error or timeout), rejected by the SSRF guard",
        )
    if target.verdict is not UrlVerdict.ALLOWED:
        logger.warning(
            "Webhook target rejected (private/reserved): %s -> %s", check.name, _log_host(url)
        )
        return False, "Webhook target is private/reserved (not allowed)"

    payload = {
        "alert_rule": rule.name,
        **msg,
    }

    try:
        # pinned_client connects to an address check_target checked, not to whatever a
        # second lookup answers. check_target has read the URL with httpx already; the
        # client sits inside the try because building it can fail on an unusable proxy
        # setting from the environment (HTTPS_PROXY=ftp://..., NO_PROXY=host:abc).
        with pinned_client(url, target) as client:
            resp = client.post(url, json=payload, timeout=10, follow_redirects=False)
        if resp.status_code < 300:
            logger.info("Webhook sent: %s -> %s", check.name, _log_host(url))
            return True, None
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        logger.error("Webhook failed: %s -> %s: %s", check.name, _log_host(url), exc)
        return False, _webhook_failure(exc)


def _email_failure(exc: Exception, *, in_starttls: bool, loading_ca: bool) -> str:
    """The alert-log reason for a failed send: a fixed text per kind of error. The
    exception text (mail server replies, host names) goes to the service log only."""
    # Every smtplib error and ssl.SSLError is an OSError as well, so the order matters.
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return f"SMTP authentication failed ({exc.smtp_code})"
    if isinstance(
        exc,
        (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError),
    ):
        return "SMTP server refused the message"
    # SMTPNotSupportedError means "no STARTTLS" only from starttls(); login() and the
    # send raise it for a missing AUTH or SMTPUTF8 extension. An OSError while loading
    # SMTP_CA_FILE (missing, unreadable) is a TLS setup failure, not a connection one.
    if (
        isinstance(exc, ssl.SSLError)
        or (in_starttls and isinstance(exc, smtplib.SMTPNotSupportedError))
        or (loading_ca and isinstance(exc, OSError))
    ):
        return "SMTP TLS failed"
    if isinstance(exc, TimeoutError):
        return "SMTP connection timed out"
    if isinstance(exc, smtplib.SMTPException):
        return f"SMTP error ({type(exc).__name__})"
    if isinstance(exc, OSError):
        return "SMTP connection failed"
    return f"SMTP error ({type(exc).__name__})"


def _send_email(
    config: dict,
    rule: MonitorAlertRule,
    check: MonitorCheck,
    msg: dict,
) -> tuple[bool, str | None]:
    """Sends the alert via email."""
    recipients = config.get("recipients") or config.get("to") or []
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",") if r.strip()]
    if not recipients:
        return False, "No recipients configured"

    rule_host = str(config.get("smtp_host") or "").strip()
    # SMTP_USER/SMTP_PASSWORD belong to the relay in SMTP_HOST; a rule naming another host
    # logs in with its own credentials only, so the global password never reaches that host.
    env_relay = not rule_host or rule_host.lower() == SMTP_HOST.strip().lower()
    smtp_host = rule_host or SMTP_HOST
    smtp_port = int(config.get("smtp_port") or SMTP_PORT)
    smtp_user = config.get("smtp_user") or (SMTP_USER if env_relay else "")
    smtp_pass = config.get("smtp_password") or (SMTP_PASSWORD if env_relay else "")

    if not smtp_host:
        return False, "SMTP not configured (SMTP_HOST missing)"

    message = MIMEMultipart("alternative")
    message["Subject"] = msg["subject"]
    message["From"] = config.get("from", SMTP_FROM)
    message["To"] = ", ".join(recipients)
    message.attach(MIMEText(msg["text"], "plain"))

    in_starttls = loading_ca = False
    try:
        # Port 465 = implicit TLS (SMTPS): the connection must be wrapped from the
        # start (SMTP_SSL). Every other port upgrades via STARTTLS. Both use a
        # verifying context (create_default_context checks cert + hostname), so a
        # MITM cannot strip TLS and harvest the login credentials (3.24).
        ctx = ssl.create_default_context()
        if SMTP_CA_FILE:
            # A relay with a private CA (any relay, a rule's own included): added to the system
            # CAs, checks stay on. A file that cannot be loaded stops the send before connecting.
            loading_ca = True
            ctx.load_verify_locations(cafile=SMTP_CA_FILE)
            loading_ca = False
        if smtp_port == 465:
            smtp_ctx = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10, context=ctx)
        else:
            smtp_ctx = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
        with smtp_ctx as server:
            if smtp_port != 465:
                # STARTTLS on EVERY non-implicit-TLS port (not just 587): fails
                # closed if the server offers no TLS, so smtp_user/smtp_password
                # never go over a plaintext/unverified connection (25/2525/...).
                in_starttls = True
                server.starttls(context=ctx)
                in_starttls = False
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(message)
        logger.info("E-Mail gesendet: %s -> %s", check.name, recipients)
        return True, None
    except Exception as exc:
        logger.error("Email failed: %s: %s", check.name, exc)
        return False, _email_failure(exc, in_starttls=in_starttls, loading_ca=loading_ca)
