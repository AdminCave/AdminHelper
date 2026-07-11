# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.auth import ApiKeyOrUser, get_current_admin
from app.core.database import get_db
from app.core.events import fire_event
from app.core.pagination import paginate
from app.core.request_context import actor_from_request
from app.modules.audit import service as audit
from app.modules.connections.models import Connection
from app.modules.connections.schemas import ConnectionCreate, ConnectionUpdate, ImportRequest
from app.modules.users.models import User

router = APIRouter(prefix="/api/connections", tags=["connections"])

read_dep = ApiKeyOrUser(require_write=False)
# write = a read_write API key OR an admin JWT user (BY DESIGN — read_write keys
# are documented to read AND write). require_admin gates only the JWT path; the
# API-key path is gated by require_write. Pinned by tests/test_connections_authz.py.
write_dep = ApiKeyOrUser(require_write=True, require_admin=True)


def _scope_connections(query, auth):
    """Restrict a Connection query to what the calling principal may see.

    Non-admin users are isolated to the connections of their assigned servers
    (mirrors the FRP-visitor scoping in frp/generate_router.py — the same
    per-user isolation invariant); a server-bound API key is restricted to its
    server. Admin users and global (no server_id) API keys are unrestricted by
    design. Connections with no server_id are admin/global-only for non-admins.
    """
    user, api_key = auth
    if user is not None and not user.is_admin:
        server_ids = [s.id for s in user.servers]
        return query.filter(Connection.server_id.in_(server_ids))
    if api_key is not None and api_key.server_id:
        return query.filter(Connection.server_id == api_key.server_id)
    return query


@router.get("", response_model=list[dict[str, Any]])
def get_connections(
    response: Response,
    db: Session = Depends(get_db),
    auth=Depends(read_dep),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    # Pagination strictly AFTER the per-user/key scoping: LIMIT/OFFSET and
    # X-Total-Count must apply to the visible subset, not the full table.
    query = _scope_connections(db.query(Connection), auth).order_by(Connection.name, Connection.id)
    connections = paginate(query, response, limit, offset).all()
    return [c.to_dict() for c in connections]


@router.post("", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_connection(
    connection: ConnectionCreate,
    request: Request,
    db: Session = Depends(get_db),
    _auth=Depends(write_dep),
):
    data = connection.model_dump()
    data["id"] = str(uuid.uuid4())
    conn = Connection.from_dict(data)
    db.add(conn)
    db.commit()
    db.refresh(conn)
    result = conn.to_dict()
    fire_event("connection.created", result)
    audit.record(
        db,
        "connection.created",
        actor=actor_from_request(request),
        object_type="connection",
        object_id=result["id"],
        object_label=result.get("name"),
    )
    return result


@router.put("/{conn_id}", response_model=dict[str, Any])
def update_connection(
    conn_id: str,
    connection: ConnectionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _auth=Depends(write_dep),
):
    # Scope the write path like GET/touch: a server-bound key must not update
    # connections of other servers it cannot even see (invariant holds symmetric
    # to the read path, not just for the JWT).
    conn = _scope_connections(db.query(Connection), _auth).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden"
        )
    conn.update_from_dict(connection.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(conn)
    result = conn.to_dict()
    fire_event("connection.updated", result)
    audit.record(
        db,
        "connection.updated",
        actor=actor_from_request(request),
        object_type="connection",
        object_id=conn_id,
        object_label=result.get("name"),
    )
    return result


@router.post("/{conn_id}/touch", response_model=dict[str, Any])
def touch_connection(
    conn_id: str, request: Request, db: Session = Depends(get_db), auth=Depends(read_dep)
):
    """Setzt last_used auf jetzt. Auth: jeder Lesezugriff genuegt (Nutzung == Lesen),
    aber per-User/Key-Scope wie bei der Liste (kein Touch fremder Connections)."""
    conn = _scope_connections(db.query(Connection), auth).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden"
        )
    conn.last_used = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(conn)
    audit.record(
        db,
        "connection.accessed",
        actor=actor_from_request(request),
        object_type="connection",
        object_id=conn_id,
        object_label=conn.name,
    )
    return conn.to_dict()


@router.delete("/{conn_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    conn_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    conn = db.query(Connection).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden"
        )
    result = conn.to_dict()
    db.delete(conn)
    db.commit()
    fire_event("connection.deleted", result)
    audit.record(
        db,
        "connection.deleted",
        actor=actor_from_request(request),
        object_type="connection",
        object_id=conn_id,
        object_label=result.get("name"),
    )


@router.get("/export", response_class=Response)
def export_connections(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)
):
    connections = db.query(Connection).all()
    data = json.dumps([c.to_dict() for c in connections], ensure_ascii=False, indent=2)
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="connections.json"'},
    )


@router.post("/import")
def import_connections(
    req: ImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    # Validate every entry through ConnectionCreate BEFORE touching the DB: the
    # raw list bypassed schema validation, so an invalid kind/port (or a missing
    # name) used to land in the table or blow up with a 500 mid-loop. Validate
    # all-or-nothing — otherwise a "replace" import with bad input would wipe
    # every existing connection and import nothing (data loss).
    validated: list[dict] = []
    errors: list[dict] = []
    for idx, conn_data in enumerate(req.connections):
        try:
            payload = ConnectionCreate(**conn_data).model_dump()
        except ValidationError as exc:
            errors.append(
                {
                    "index": idx,
                    "name": conn_data.get("name") if isinstance(conn_data, dict) else None,
                    "errors": exc.errors(include_url=False),
                }
            )
            continue
        payload["id"] = str(uuid.uuid4())
        validated.append(payload)

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "Import enthält ungültige Einträge", "rejected": errors},
        )

    if req.mode == "replace":
        db.query(Connection).delete()

    imported = []
    for payload in validated:
        conn = Connection.from_dict(payload)
        db.add(conn)
        imported.append(conn)

    db.commit()
    fire_event("connections.imported", {"count": len(imported), "mode": req.mode})
    audit.record(
        db,
        "connections.imported",
        actor=actor_from_request(request),
        object_type="connection",
        detail=f"{len(imported)} connections ({req.mode})",
    )
    return {"imported": len(imported), "mode": req.mode}
