# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The objects the checks name, with their damped state (ADR 0004 §5, R-1559)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import case
from sqlalchemy.orm import Session

from ah_common.pagination import paginate
from app.core.auth import require_internal
from app.core.bounds import Offset
from app.core.database import get_db
from app.core.time import iso_utc, utcnow_naive
from app.exception_scope import load_no_notify, narrowest
from app.models import MonitorCheck, MonitorException, MonitorObjectState, MonitorState
from app.objects import SEVERITY
from app.schemas import MonitorObjectOut

router = APIRouter()

# A status outside SEVERITY counts as the worst, as in app.objects._rank.
_WORST_FIRST = case(
    {status: rank for rank, status in enumerate(SEVERITY)},
    value=MonitorObjectState.status,
    else_=0,
)
# An object a setting excludes comes last, whatever its status (R-1636).
_EXCLUDED_LAST = case((MonitorObjectState.excluded.is_(None), 0), else_=1)


def _exception(
    obj: MonitorObjectState,
    check_type: str,
    server_id: str | None,
    exceptions: list[MonitorException],
    now: datetime,
) -> dict | None:
    """What keeps the object out (R-1636): the setting that excludes it, which counts as an
    object scope and beats every exception row, else the narrowest exception in force over
    its check. An exception does not change the object's status or place."""
    if obj.excluded is not None:
        return {
            "source": "setting",
            "effect": "skip",
            "setting": obj.excluded,
            "id": None,
            "scopeKind": None,
            "reason": None,
        }
    exc = narrowest(exceptions, obj.check_id, check_type, server_id, now)
    if exc is None:
        return None
    return {
        "source": "exception",
        "effect": exc.effect,
        "setting": None,
        "id": exc.id,
        "scopeKind": exc.scope_kind,
        "reason": exc.reason,
    }


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
    """The objects of the checks, worst first, then by name, the ones a setting excludes
    last; gone ones only on request. Each names the setting or exception that keeps it out."""
    q = (
        db.query(
            MonitorObjectState,
            MonitorCheck.name,
            MonitorCheck.server_id,
            MonitorCheck.check_type,
            MonitorState.last_check,
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
        _EXCLUDED_LAST,
        _WORST_FIRST,
        MonitorObjectState.name,
        MonitorObjectState.check_id,
        MonitorObjectState.object_key,
    )
    rows = paginate(q.order_by(*order), response, limit, offset).all()
    # One query for the whole page, matched to its objects after paging.
    exceptions, now = load_no_notify(db), utcnow_naive()
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
            "exception": _exception(obj, check_type, check_server, exceptions, now),
        }
        for obj, check_name, check_server, check_type, last_check in rows
    ]
