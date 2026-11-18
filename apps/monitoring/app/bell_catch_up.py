# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Catch-up of the bell (docs/features/kern-monitoring-47.md, R-1572).

process_alert commits the claim before the hub POST (at most once); a POST the hub
does not accept hands back only the bell's slot, and the next evaluation of the
check finds nothing new to report. catch_up_bell, the job system:bell-catch-up,
sends what the bell lags behind: for an enabled check the status last reported,
for a disabled one the all-clear of the problem the bell still shows. At most
CATCH_UP_MAX checks per run, oldest first; the outbox (R-1561) replaces it later.
"""

from __future__ import annotations

import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import alerter
from app.core import database
from app.core.time import utcnow_naive
from app.models import MonitorCheck, MonitorState

logger = logging.getLogger(__name__)

# Checks one run sends at most: a hub that is down costs at most this many POSTs
# (5 s timeout each) per run.
CATCH_UP_MAX = 20
CATCH_UP_SECONDS = 60

_PROBLEMS = ("warning", "critical")


def closed_message(check: MonitorCheck, what: str) -> dict:
    """The bell's all-clear of a check taken out of monitoring (``what``: disabled,
    deleted): its alarm is closed, the check is not OK again."""
    name = alerter.subject_safe(check.name)
    return {
        "subject": f"[AdminHelper Monitor] {name}: check {what}",
        "text": f"Check: {check.name} ({check.check_type})\n"
        f"The check was {what}; its alarm is closed.",
    }


def lag_target(check: MonitorCheck, state: MonitorState) -> str | None:
    """The status the bell still has to get of the check, None when it shows what
    it should. An enabled check: the status last reported, when the normal dispatch
    has nothing open (``status`` reports as ``notified_status``), the bell would
    show it and does not yet. A disabled one: ok while the bell shows a problem."""
    if not check.enabled:
        return "ok" if state.hub_status in _PROBLEMS else None
    notified = state.notified_status
    if notified not in ("ok", *_PROBLEMS) or alerter.alert_status(state.status) != notified:
        return None
    if alerter.hub_decision(state.hub_status, notified, check.severity) != "emit":
        return None
    shown = alerter.bell_record(notified, check.severity, state.hub_sent_at, utcnow_naive())[0]
    return None if shown == state.hub_status else notified


def _candidates(db: Session) -> list[str]:
    """Ids of the checks that may lag, oldest state first; lag_target decides. A
    check with a reservation in flight already carries what it is about to show."""
    rows = (
        db.query(MonitorState.check_id)
        .join(MonitorCheck, MonitorCheck.id == MonitorState.check_id)
        .filter(
            or_(
                MonitorState.hub_status.in_(_PROBLEMS),
                MonitorState.notified_status.in_(_PROBLEMS),
            )
        )
        .order_by(MonitorState.since, MonitorState.check_id)
        .all()
    )
    return [row.check_id for row in rows]


def _catch_up_one(db: Session, check_id: str) -> bool:
    """Send what the bell lags behind of one check; False when nothing was sent
    (another session holds the row, nothing lags, the check is muted)."""
    state = (
        db.query(MonitorState)
        .filter(MonitorState.check_id == check_id)
        .with_for_update(skip_locked=True)
        .first()
    )
    check = db.get(MonitorCheck, check_id)
    if state is None or check is None:
        db.rollback()
        return False
    target = lag_target(check, state)
    now = utcnow_naive()
    if target is None or alerter.muted_reason(db, check, now) is not None:
        db.rollback()
        return False

    old = alerter.alert_status(alerter.reported_status(state.hub_status))
    severity = alerter.bell_severity(state.hub_status, old, target, check.severity)
    if not check.enabled:
        msg = closed_message(check, "disabled")
    else:
        msg = alerter.build_message(db, check, old, target)
    # Reserve the slot as process_alert does, so a dispatch that starts during the
    # POST reads what this one is about to show.
    before = (state.hub_status, state.hub_sent_at)
    reserved = alerter.bell_record(target, check.severity, state.hub_sent_at, now)
    state.hub_status, state.hub_sent_at = reserved
    db.commit()

    if alerter.emit_to_hub(check, old, target, msg, severity=severity):
        return True
    alerter.release_hub_slot(db, check_id, reserved, before)
    db.commit()
    return True


def catch_up_bell() -> None:
    """The job system:bell-catch-up: send at most CATCH_UP_MAX lagging checks to the
    bell, oldest first. Each check is claimed under its own row lock (FOR UPDATE
    SKIP LOCKED), so a dispatch that holds the row is left alone. A failed POST
    hands the slot back and counts against the cap: the check waits for the next
    run. Errors are logged and rolled back."""
    db = database.SessionLocal()
    try:
        ids = _candidates(db)
        db.rollback()
        sent = 0
        for check_id in ids:
            if sent >= CATCH_UP_MAX:
                break
            if _catch_up_one(db, check_id):
                sent += 1
    except Exception:
        logger.exception("Bell catch-up failed")
        db.rollback()
    finally:
        db.close()
