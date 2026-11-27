# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exception CRUD (R-1636, ADR 0004 §7): where an exception applies, what it does and for
how long. DELETE ends an exception instead of deleting it: an ended one no longer applies
and stays readable until the history cleanup removes it
(scheduler.EXCEPTION_ENDED_RETENTION_DAYS). The /maintenance facade works on the same
rows (routers/maintenance.py).

A skip made, changed or ended here switches its check as the check's own switch does
(app.check_switch, R-1637): the scheduler, the all-clear and the fresh start follow."""

from __future__ import annotations

import json
import uuid
from typing import NamedTuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.check_switch import AllClear, send_all_clear, started, stopped
from app.core.actor import Actor, request_actor
from app.core.auth import require_internal
from app.core.database import get_db
from app.core.time import utcnow_naive
from app.exception_scope import OBJECT_KINDS, check_runs, check_skips
from app.models import MonitorCheck, MonitorException
from app.scheduler import add_check, remove_check
from app.schemas import STANDING_EFFECTS, ExceptionInput, ExceptionOut

router = APIRouter()


class _Switch(NamedTuple):
    """A check a skip started or stopped, and the all-clear it owes the bell."""

    check: MonitorCheck
    clear: AllClear | None


def _apply(db: Session, row: MonitorException, data: ExceptionInput) -> None:
    check = None
    if data.scope_kind in ("check", "object"):
        check = db.get(MonitorCheck, data.scope_value)
        if check is None:
            raise HTTPException(422, "Unknown check")
    if data.scope_kind == "object":
        owner = OBJECT_KINDS[data.object_kind].check_type
        if check.check_type != owner:
            raise HTTPException(422, f"Objects of kind {data.object_kind} belong to {owner} checks")
    if data.effect == "skip" and data.enabled:
        if any(skip.id != row.id for skip in check_skips(db, check.id)):
            raise HTTPException(409, "The check has a skip in force")
    row.scope_kind = data.scope_kind
    row.check_id = None
    row.check_type = None
    row.server_id = None
    if check is not None:
        row.check_id = check.id
        # The check's server, for the server filter of the list and the server cleanup.
        row.server_id = check.server_id
    elif data.scope_kind == "check_type":
        row.check_type = data.scope_value
    elif data.scope_kind == "server":
        row.server_id = data.scope_value
    row.object_kind = data.object_kind
    row.object_pattern = data.object_pattern
    row.effect = data.effect
    row.duration_kind = data.duration_kind
    # Only the fields of the duration kind are stored, as for a maintenance window.
    once = data.duration_kind == "once"
    weekly = data.duration_kind == "weekly"
    row.starts_at = data.starts_at if once else None
    row.ends_at = data.ends_at if once else None
    row.weekdays = json.dumps(data.weekdays) if weekly else None
    row.start_time = data.start_time if weekly else None
    row.duration_minutes = data.duration_minutes if weekly else None
    row.timezone = data.timezone
    row.reason = data.reason
    row.enabled = data.enabled


def _open(db: Session, exception_id: str) -> MonitorException:
    """The exception with this id, as long as it has not ended."""
    row = db.get(MonitorException, exception_id)
    if row is None:
        raise HTTPException(404, "Exception not found")
    if row.ended_at is not None:
        raise HTTPException(409, "Exception has ended")
    return row


def _before(db: Session, row: MonitorException) -> tuple[MonitorCheck | None, bool]:
    """The check a skip names and whether it runs, taken before the skip changes; no check
    for another effect, which does not decide whether a check runs."""
    if row.effect != "skip":
        return None, False
    check = db.get(MonitorCheck, row.check_id)
    return check, check_runs(db, check)


def _follow(db: Session, check: MonitorCheck | None, ran: bool) -> _Switch | None:
    """Brings a check in line with its skip that came, changed or ended: one that stopped
    running owes the bell its all-clear, one that runs again starts fresh."""
    if check is None:
        return None
    db.flush()
    runs = check_runs(db, check)
    if runs == ran:
        return None
    if runs:
        started(db, check)
        return _Switch(check, None)
    return _Switch(check, stopped(db, check))


def _after_commit(db: Session, switch: _Switch | None, background_tasks: BackgroundTasks) -> None:
    """The scheduler in line with the committed check, the all-clear after the answer."""
    if switch is None:
        return
    check = switch.check
    if check_runs(db, check):
        add_check(check.id, check.interval, check.check_type)
    else:
        remove_check(check.id)
    if switch.clear is not None:
        background_tasks.add_task(send_all_clear, switch.clear)


@router.get(
    "/exceptions",
    response_model=list[ExceptionOut],
    dependencies=[Depends(require_internal)],
)
def list_exceptions(
    include_ended: bool = False,
    server_id: str | None = None,
    check_id: str | None = None,
    db: Session = Depends(get_db),
):
    """Lists the exceptions, oldest first; ended ones only with include_ended."""
    query = db.query(MonitorException)
    if not include_ended:
        query = query.filter(MonitorException.ended_at.is_(None))
    if server_id is not None:
        query = query.filter(MonitorException.server_id == server_id)
    if check_id is not None:
        query = query.filter(MonitorException.check_id == check_id)
    rows = query.order_by(MonitorException.created_at, MonitorException.id).all()
    return [r.to_dict() for r in rows]


@router.post(
    "/exceptions",
    status_code=status.HTTP_201_CREATED,
    response_model=ExceptionOut,
    dependencies=[Depends(require_internal)],
)
def create_exception(
    data: ExceptionInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Actor = Depends(request_actor),
):
    """Creates an exception."""
    row = MonitorException(
        id=str(uuid.uuid4()), origin="api", created_by=actor.name, created_by_id=actor.id
    )
    _apply(db, row, data)
    check, ran = _before(db, row)
    db.add(row)
    switch = _follow(db, check, ran)
    db.commit()
    db.refresh(row)
    _after_commit(db, switch, background_tasks)
    return row.to_dict()


@router.put(
    "/exceptions/{exception_id}",
    response_model=ExceptionOut,
    dependencies=[Depends(require_internal)],
)
def update_exception(
    exception_id: str,
    data: ExceptionInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Actor = Depends(request_actor),
):
    """Full update of an exception (same payload as create); an ended one is 409. Its
    effect stays, and a skip or no_rating keeps its check (422)."""
    row = _open(db, exception_id)
    if data.effect != row.effect or (
        row.effect in STANDING_EFFECTS and data.scope_value != row.check_id
    ):
        raise HTTPException(422, "An exception keeps its effect, a skip or no_rating its check")
    check, ran = _before(db, row)
    _apply(db, row, data)
    row.updated_at = utcnow_naive()
    row.updated_by = actor.name
    row.updated_by_id = actor.id
    switch = _follow(db, check, ran)
    db.commit()
    db.refresh(row)
    _after_commit(db, switch, background_tasks)
    return row.to_dict()


@router.delete(
    "/exceptions/{exception_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal)],
)
def end_exception(
    exception_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Actor = Depends(request_actor),
):
    """Ends an exception: it no longer applies and stays readable with include_ended."""
    row = _open(db, exception_id)
    check, ran = _before(db, row)
    row.ended_at = utcnow_naive()
    row.ended_by = actor.name
    row.ended_by_id = actor.id
    switch = _follow(db, check, ran)
    db.commit()
    _after_commit(db, switch, background_tasks)
