# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The objects the checks name, with their damped state (ADR 0004 §5, R-1559)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, case
from sqlalchemy.orm import Session

from ah_common.pagination import paginate
from app.core.auth import require_internal
from app.core.bounds import Offset
from app.core.database import get_db
from app.core.time import iso_utc, utcnow_naive
from app.exception_scope import OBJECT_KINDS, load_no_notify, load_skips, narrowest, skipped
from app.models import (
    UNSTABLE_OBJECT_KINDS,
    MonitorCheck,
    MonitorException,
    MonitorObjectState,
    MonitorState,
)
from app.objects import NOT_COLLECTED, SEVERITY
from app.schemas import MonitorObjectOut

router = APIRouter()

# The settings that exclude objects (R-1636). Any other mark is the id of the no_rating
# exception that excluded the object (R-1637).
_SETTINGS = frozenset(kind.list_key for kind in OBJECT_KINDS.values())
_NOT_CHECKED = "Not checked by exception"

# A status outside SEVERITY counts as the worst, as in app.objects._rank. An object of a
# check a skip keeps from running counts as what it shows: not collected (R-1637).
_WORST_FIRST = case(
    (skipped, SEVERITY.index(NOT_COLLECTED)),
    else_=case(
        {status: rank for rank, status in enumerate(SEVERITY)},
        value=MonitorObjectState.status,
        else_=0,
    ),
)
# An object a setting or an exception excludes comes last, whatever its status (R-1636,
# R-1637), and so do the objects of a check a skip keeps from running.
_EXCLUDED_LAST = case((and_(MonitorObjectState.excluded.is_(None), ~skipped), 0), else_=1)


def _mark(exc: MonitorException) -> dict:
    return {
        "source": "exception",
        "effect": exc.effect,
        "setting": None,
        "id": exc.id,
        "scopeKind": exc.scope_kind,
        "reason": exc.reason,
        "unstable": exc.object_kind in UNSTABLE_OBJECT_KINDS
        if exc.scope_kind == "object"
        else None,
    }


def _exception(
    obj: MonitorObjectState,
    check_type: str,
    server_id: str | None,
    skip: MonitorException | None,
    marked: dict[str, MonitorException],
    exceptions: list[MonitorException],
    now: datetime,
) -> dict | None:
    """What keeps the object out: the skip in force on its check (R-1637), else what its
    check excluded it by at its last run (the mark), else the narrowest exception in force
    over its check. A setting counts as an object scope (R-1636); a no_rating exception
    names the object until the check runs again, ended or not. An exception over the check
    does not change the object's status or place."""
    if skip is not None:
        return _mark(skip)
    if obj.excluded in _SETTINGS:
        return {
            "source": "setting",
            "effect": "skip",
            "setting": obj.excluded,
            "id": None,
            "scopeKind": None,
            "reason": None,
            "unstable": None,
        }
    if obj.excluded is not None:
        exc = marked.get(obj.excluded)
        if exc is not None:
            return _mark(exc)
        # Its row is gone (ended rows are purged after a retention): what the mark tells.
        return {
            "source": "exception",
            "effect": "no_rating",
            "setting": None,
            "id": obj.excluded,
            "scopeKind": "object",
            "reason": None,
            "unstable": obj.kind in UNSTABLE_OBJECT_KINDS,
        }
    exc = narrowest(exceptions, obj.check_id, check_type, server_id, now)
    return None if exc is None else _mark(exc)


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
    """The objects of the checks, worst first, then by name, the ones a setting or an
    exception excludes last; gone ones only on request. The objects of a check a skip keeps
    from running show not collected and come last. Each names the setting or exception
    that keeps it out."""
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
    # One query each for the whole page, matched to its objects after paging.
    exceptions, skips, now = load_no_notify(db), load_skips(db), utcnow_naive()
    ids = {obj.excluded for obj, *_ in rows if obj.excluded not in _SETTINGS} - {None}
    marked = {}
    if ids:
        marked = {e.id: e for e in db.query(MonitorException).filter(MonitorException.id.in_(ids))}
    entries = []
    for obj, check_name, check_server, check_type, last_check in rows:
        skip = skips.get(obj.check_id)
        entry = {
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
            "exception": _exception(obj, check_type, check_server, skip, marked, exceptions, now),
        }
        if skip is not None:
            # The check does not run: not the state it froze (ADR 0004 §12.2), but not
            # collected, at the latest since the skip.
            since = max(obj.since, skip.created_at) if skip.created_at else obj.since
            entry.update(
                status=NOT_COLLECTED, reason=_NOT_CHECKED, since=iso_utc(since), badSince=None
            )
        entries.append(entry)
    return entries
