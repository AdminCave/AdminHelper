# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Maintenance-window CRUD (collect-but-mute windows, see app/maintenance.py)."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import require_internal
from app.core.database import get_db
from app.models import MonitorMaintenance
from app.schemas import MaintenanceInput

router = APIRouter()


def _apply(row: MonitorMaintenance, data: MaintenanceInput) -> None:
    row.server_id = data.server_id
    row.note = data.note
    row.kind = data.kind
    # Symmetric kind-dependent nulling: a weekly payload with stray once
    # fields (or vice versa) must not persist ghost values the UI echoes back.
    row.starts_at = data.starts_at if data.kind == "once" else None
    row.ends_at = data.ends_at if data.kind == "once" else None
    row.weekdays = json.dumps(data.weekdays) if data.kind == "weekly" else None
    row.start_time = data.start_time if data.kind == "weekly" else None
    row.duration_minutes = data.duration_minutes if data.kind == "weekly" else None
    row.timezone = data.timezone
    row.enabled = data.enabled


@router.get("/maintenance", dependencies=[Depends(require_internal)])
def list_maintenance(db: Session = Depends(get_db)):
    """Lists all maintenance windows."""
    rows = db.query(MonitorMaintenance).order_by(MonitorMaintenance.created_at).all()
    return [r.to_dict() for r in rows]


@router.post(
    "/maintenance", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal)]
)
def create_maintenance(data: MaintenanceInput, db: Session = Depends(get_db)):
    """Creates a maintenance window."""
    row = MonitorMaintenance(id=str(uuid.uuid4()))
    _apply(row, data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.put("/maintenance/{maintenance_id}", dependencies=[Depends(require_internal)])
def update_maintenance(maintenance_id: str, data: MaintenanceInput, db: Session = Depends(get_db)):
    """Full update of a maintenance window (same payload as create)."""
    row = db.query(MonitorMaintenance).filter(MonitorMaintenance.id == maintenance_id).first()
    if not row:
        raise HTTPException(404, "Maintenance window not found")
    _apply(row, data)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.delete(
    "/maintenance/{maintenance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal)],
)
def delete_maintenance(maintenance_id: str, db: Session = Depends(get_db)):
    """Deletes a maintenance window."""
    deleted = db.query(MonitorMaintenance).filter(MonitorMaintenance.id == maintenance_id).delete()
    if not deleted:
        raise HTTPException(404, "Maintenance window not found")
    db.commit()
