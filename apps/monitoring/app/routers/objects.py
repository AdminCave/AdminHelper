# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The objects the checks name, with their damped state (ADR 0004 §5, R-1559)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import case
from sqlalchemy.orm import Session

from app.core.auth import require_internal
from app.core.bounds import Offset
from app.core.database import get_db
from app.core.pagination import paginate
from app.core.time import iso_utc
from app.models import MonitorCheck, MonitorObjectState, MonitorState
from app.objects import SEVERITY
from app.schemas import MonitorObjectOut

router = APIRouter()

# A status outside SEVERITY counts as the worst, as in app.objects._rank.
_WORST_FIRST = case(
    {status: rank for rank, status in enumerate(SEVERITY)},
    value=MonitorObjectState.status,
    else_=0,
)


@router.get(
    "/objects",
    response_model=list[MonitorObjectOut],
    dependencies=[Depends(require_internal)],
)
def list_objects(
    response: Response,
    server_id: str | None = Query(None),
    check_id: str | None = Query(None),
    kind: str | None = Query(None),
    include_gone: bool = Query(False),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: Annotated[Offset, Query()] = 0,
    db: Session = Depends(get_db),
):
    """The objects of the checks, worst first, then by name; gone ones only on request."""
    q = (
        db.query(
            MonitorObjectState, MonitorCheck.name, MonitorCheck.server_id, MonitorState.last_check
        )
        .join(MonitorCheck, MonitorCheck.id == MonitorObjectState.check_id)
        .outerjoin(MonitorState, MonitorState.check_id == MonitorObjectState.check_id)
    )
    if server_id:
        q = q.filter(MonitorCheck.server_id == server_id)
    if check_id:
        q = q.filter(MonitorObjectState.check_id == check_id)
    if kind:
        q = q.filter(MonitorObjectState.kind == kind)
    if not include_gone:
        q = q.filter(MonitorObjectState.gone_at.is_(None))
    order = (
        _WORST_FIRST,
        MonitorObjectState.name,
        MonitorObjectState.check_id,
        MonitorObjectState.object_key,
    )
    rows = paginate(q.order_by(*order), response, limit, offset).all()
    return [
        {
            "checkId": obj.check_id,
            "checkName": check_name,
            "serverId": check_server,
            "key": obj.object_key,
            "kind": obj.kind,
            "name": obj.name,
            "status": obj.status,
            "reason": obj.reason,
            "since": iso_utc(obj.since),
            "badSince": iso_utc(obj.bad_since),
            "stable": obj.stable,
            "goneAt": iso_utc(obj.gone_at),
            "lastCheck": iso_utc(last_check),
        }
        for obj, check_name, check_server, last_check in rows
    ]
