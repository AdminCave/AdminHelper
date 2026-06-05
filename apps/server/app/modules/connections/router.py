# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.auth import ApiKeyOrUser, get_current_admin
from app.core.database import get_db
from app.core.events import fire_event
from app.modules.connections.models import Connection
from app.modules.connections.schemas import ConnectionCreate, ConnectionUpdate, ImportRequest
from app.modules.users.models import User

router = APIRouter(prefix="/api/connections", tags=["connections"])

read_dep = ApiKeyOrUser(require_write=False)
write_dep = ApiKeyOrUser(require_write=True, require_admin=True)


@router.get("", response_model=list[dict[str, Any]])
def get_connections(db: Session = Depends(get_db), auth=Depends(read_dep)):
    connections = db.query(Connection).all()
    return [c.to_dict() for c in connections]


@router.post("", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_connection(connection: ConnectionCreate, db: Session = Depends(get_db), _auth=Depends(write_dep)):
    data = connection.model_dump()
    data["id"] = str(uuid.uuid4())
    conn = Connection.from_dict(data)
    db.add(conn)
    db.commit()
    db.refresh(conn)
    result = conn.to_dict()
    fire_event("connection.created", result)
    return result


@router.put("/{conn_id}", response_model=dict[str, Any])
def update_connection(conn_id: str, connection: ConnectionUpdate, db: Session = Depends(get_db), _auth=Depends(write_dep)):
    conn = db.query(Connection).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden")
    conn.update_from_dict(connection.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(conn)
    result = conn.to_dict()
    fire_event("connection.updated", result)
    return result


@router.post("/{conn_id}/touch", response_model=dict[str, Any])
def touch_connection(conn_id: str, db: Session = Depends(get_db), _auth=Depends(read_dep)):
    """Setzt last_used auf jetzt. Auth: jeder Lesezugriff genuegt (Nutzung == Lesen)."""
    conn = db.query(Connection).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden")
    conn.last_used = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(conn)
    return conn.to_dict()


@router.delete("/{conn_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(conn_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    conn = db.query(Connection).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden")
    result = conn.to_dict()
    db.delete(conn)
    db.commit()
    fire_event("connection.deleted", result)


@router.get("/export", response_class=Response)
def export_connections(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    connections = db.query(Connection).all()
    data = json.dumps([c.to_dict() for c in connections], ensure_ascii=False, indent=2)
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="connections.json"'},
    )


@router.post("/import")
def import_connections(req: ImportRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    if req.mode == "replace":
        db.query(Connection).delete()

    imported = []
    for conn_data in req.connections:
        conn_data["id"] = str(uuid.uuid4())
        conn = Connection.from_dict(conn_data)
        db.add(conn)
        imported.append(conn)

    db.commit()
    fire_event("connections.imported", {"count": len(imported), "mode": req.mode})
    return {"imported": len(imported), "mode": req.mode}
