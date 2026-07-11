# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only audit-log API (admin only). The trail is append-only — there are
deliberately no write/delete endpoints here; rows are written by
app.modules.audit.service.record() and pruned only by the retention job."""

from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin
from app.core.database import get_db
from app.core.pagination import paginate
from app.modules.audit.models import AuditLog

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[dict[str, Any]])
def list_audit(
    response: Response,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
    action: str | None = Query(None),
    actor_type: str | None = Query(None),
    object_type: str | None = Query(None),
    object_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = Query(None, description="Free-text match on actor/object label"),
    # Default cap (unlike the legacy None default on the small servers/hooks lists): the audit log
    # grows for AUDIT_RETENTION_DAYS (365), so an unlimited fetch would materialize hundreds of
    # thousands of rows. Callers paginate with offset for more (5.28).
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List audit entries, newest first, with optional filters."""
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor_type:
        query = query.filter(AuditLog.actor_type == actor_type)
    if object_type:
        query = query.filter(AuditLog.object_type == object_type)
    if object_id:
        query = query.filter(AuditLog.object_id == object_id)
    if status_filter:
        query = query.filter(AuditLog.status == status_filter)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(AuditLog.actor_label.ilike(like), AuditLog.object_label.ilike(like))
        )

    # Deterministic order (timestamp can tie at second/sub-second granularity, so
    # break ties on the monotonic id) — required for stable pagination.
    query = query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
    rows = paginate(query, response, limit, offset).all()
    return [r.to_dict() for r in rows]
