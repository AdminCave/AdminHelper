# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The admin's switch of a check (R-1637): off is a skip exception, on ends it.

The column enabled stays the switch of the system (module and template sync); a check runs
while it is on and no skip is in force (app.exception_scope). Nothing here commits or
touches the scheduler: the route commits and then brings the scheduler in line with the
committed check, so a failed commit leaves the job as it was."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.alerter import bell_record, emit_to_hub, release_hub_slot
from app.bell_catch_up import closed_message
from app.core import database
from app.core.actor import Actor
from app.core.time import utcnow_naive
from app.exception_scope import check_skips
from app.models import MonitorCheck, MonitorException, MonitorState
from app.module_sync import mark_module_overrides
from app.template_sync import mark_overrides

# What hub_status records of an alarm the bell shows.
BELL_PROBLEMS = ("warning", "critical")


class AllClear(NamedTuple):
    """The all-clear a switched-off check owes the bell, sent after the answer (R-1660)."""

    check: SimpleNamespace
    msg: dict
    before: tuple[str | None, datetime | None]
    reserved: tuple[str | None, datetime | None]


def stop_check(db: Session, check: MonitorCheck, actor: Actor) -> AllClear | None:
    """Switches a running check off: a skip in force, with the actor for the trail (ADR
    0004 §7); the column stays on. Returns the all-clear the bell is owed, if any."""
    db.add(
        MonitorException(
            id=str(uuid.uuid4()),
            scope_kind="check",
            check_id=check.id,
            # The check's server, for the server filter of the list and the server cleanup.
            server_id=check.server_id,
            effect="skip",
            duration_kind="permanent",
            origin="api",
            created_by=actor.name,
            created_by_id=actor.id,
        )
    )
    state = db.get(MonitorState, check.id)
    if state is None or state.hub_status not in BELL_PROBLEMS:
        return None
    # Switched off while the bell shows its alarm: no later run sends the all-clear, so
    # this does (R-1571). The slot is reserved in the same commit, as process_alert does,
    # so the catch-up job does not send it a second time meanwhile; the all-clear counts
    # as reported.
    before = (state.hub_status, state.hub_sent_at)
    reserved = bell_record("ok", check.severity, state.hub_sent_at, utcnow_naive())
    state.hub_status, state.hub_sent_at = reserved
    state.notified_status = "ok"
    # What the all-clear needs is taken now: the session is closed when it runs.
    shown = SimpleNamespace(id=check.id, name=check.name, server_id=check.server_id)
    return AllClear(shown, closed_message(check, "disabled"), before, reserved)


def end_skips(db: Session, check: MonitorCheck, actor: Actor) -> bool:
    """Ends the skips in force on the check with the actor; True when there was one."""
    skips = check_skips(db, check.id)
    now = utcnow_naive()
    for skip in skips:
        skip.ended_at, skip.ended_by, skip.ended_by_id = now, actor.name, actor.id
    if skips:
        # The scheduler's lag counts from here, not from the last run before the skip.
        check.updated_at = now
    return bool(skips)


def start_check(db: Session, check: MonitorCheck, actor: Actor) -> None:
    """Switches a check on: ends its skips, and where the system switched its column off
    (a module instance gone, a template's enabled: false), turns the column on as before
    R-1637, marked so the next sync does not turn it off again."""
    end_skips(db, check, actor)
    if not check.enabled:
        check.enabled = True
        mark_overrides(db, check, {"enabled": True})
        mark_module_overrides(check, enabled=True)
    state = db.get(MonitorState, check.id)
    if state is not None:
        # The check starts fresh: the old status is not reported again, a problem the
        # first run finds is a new one (R-1571).
        state.status, state.fail_count, state.ok_count = "unknown", 0, 0
        state.since = utcnow_naive()


def send_all_clear(clear: AllClear) -> None:
    """The all-clear of a switched-off check, after the answer; the request's session is
    closed by then, so a refused one gives the slot back through a session of its own."""
    if emit_to_hub(clear.check, clear.before[0], "ok", clear.msg, severity=clear.before[0]):
        return
    # The catch-up job sends it on a later run (lag_target of a check that does not run).
    db = database.SessionLocal()
    try:
        release_hub_slot(db, clear.check.id, clear.reserved, clear.before)
        db.commit()
    finally:
        db.close()
