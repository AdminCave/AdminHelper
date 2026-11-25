# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Maintenance-window CRUD (collect-but-mute windows, see app/maintenance.py).

A facade over the exceptions since R-1636 (ADR 0004 §10): a window is an exception
of scope server or all, effect no_notify, once or weekly, not ended
(exception_scope.is_maintenance_shaped). Payload and answer stay as they were; DELETE
ends the window instead of deleting it."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import require_internal
from app.core.database import get_db
from app.core.time import iso_utc, utcnow_naive
from app.exception_scope import is_maintenance_shaped
from app.models import MonitorException
from app.schemas import MaintenanceInput, MaintenanceOut

router = APIRouter()


def as_maintenance(row: MonitorException) -> dict:
    """The facade's answer for a window: the shape MonitorMaintenance.to_dict has."""
    return {
        "id": row.id,
        "serverId": row.server_id if row.scope_kind == "server" else None,
        "note": row.reason,
        "kind": row.duration_kind,
        "startsAt": iso_utc(row.starts_at),
        "endsAt": iso_utc(row.ends_at),
        "weekdays": json.loads(row.weekdays) if row.weekdays else [],
        "startTime": row.start_time,
        "durationMinutes": row.duration_minutes,
        "timezone": row.timezone,
        "enabled": row.enabled,
        "createdAt": iso_utc(row.created_at),
    }


def _apply(row: MonitorException, data: MaintenanceInput) -> None:
    row.scope_kind = "all" if data.server_id is None else "server"
    row.server_id = data.server_id
    row.effect = "no_notify"
    row.reason = data.note
    row.duration_kind = data.kind
    # Symmetric kind-dependent nulling: a weekly payload with stray once
    # fields (or vice versa) must not persist ghost values the UI echoes back.
    row.starts_at = data.starts_at if data.kind == "once" else None
    row.ends_at = data.ends_at if data.kind == "once" else None
    row.weekdays = json.dumps(data.weekdays) if data.kind == "weekly" else None
    row.start_time = data.start_time if data.kind == "weekly" else None
    row.duration_minutes = data.duration_minutes if data.kind == "weekly" else None
    row.timezone = data.timezone
    row.enabled = data.enabled


def _window(db: Session, maintenance_id: str) -> MonitorException:
    """The window with this id; an exception of another shape, or an ended one, is none."""
    row = db.get(MonitorException, maintenance_id)
    if row is None or not is_maintenance_shaped(row):
        raise HTTPException(404, "Maintenance window not found")
    return row


@router.get(
    "/maintenance",
    response_model=list[MaintenanceOut],
    dependencies=[Depends(require_internal)],
)
def list_maintenance(db: Session = Depends(get_db)):
    """Lists all maintenance windows."""
    rows = (
        db.query(MonitorException)
        .filter(MonitorException.ended_at.is_(None))
        .order_by(MonitorException.created_at, MonitorException.id)
        .all()
    )
    return [as_maintenance(r) for r in rows if is_maintenance_shaped(r)]


@router.post(
    "/maintenance",
    status_code=status.HTTP_201_CREATED,
    response_model=MaintenanceOut,
    dependencies=[Depends(require_internal)],
)
def create_maintenance(data: MaintenanceInput, db: Session = Depends(get_db)):
    """Creates a maintenance window."""
    row = MonitorException(id=str(uuid.uuid4()), origin="maintenance")
    _apply(row, data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return as_maintenance(row)


@router.put(
    "/maintenance/{maintenance_id}",
    response_model=MaintenanceOut,
    dependencies=[Depends(require_internal)],
)
def update_maintenance(maintenance_id: str, data: MaintenanceInput, db: Session = Depends(get_db)):
    """Full update of a maintenance window (same payload as create)."""
    row = _window(db, maintenance_id)
    _apply(row, data)
    row.updated_at = utcnow_naive()
    db.commit()
    db.refresh(row)
    return as_maintenance(row)


@router.delete(
    "/maintenance/{maintenance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal)],
)
def delete_maintenance(maintenance_id: str, db: Session = Depends(get_db)):
    """Deletes a maintenance window."""
    # Gone for the caller (the list and the id answer as before), but the exception is
    # ended, not deleted: its trail stays (R-1636).
    row = _window(db, maintenance_id)
    row.ended_at = utcnow_naive()
    db.commit()
