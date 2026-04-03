import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from typing import Any

from app.core.auth import ApiKeyOrUser, get_current_admin
from app.core.events import fire_event
from app.modules.connections.storage import load_connections, save_connections
from app.modules.connections.schemas import ImportRequest
from app.modules.users.models import User

router = APIRouter(prefix="/api/connections", tags=["connections"])

read_dep = ApiKeyOrUser(require_write=False)
write_dep = ApiKeyOrUser(require_write=True)


@router.get("", response_model=list[dict[str, Any]])
def get_connections(auth=Depends(read_dep)):
    return load_connections()


@router.post("", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_connection(connection: dict[str, Any], auth=Depends(write_dep)):
    user, api_key = auth
    if user and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin-Rechte erforderlich")
    connection["id"] = str(uuid.uuid4())
    connections = load_connections()
    connections.append(connection)
    save_connections(connections)
    fire_event("connection.created", connection)
    return connection


@router.put("/{conn_id}", response_model=dict[str, Any])
def update_connection(conn_id: str, connection: dict[str, Any], auth=Depends(write_dep)):
    user, api_key = auth
    if user and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin-Rechte erforderlich")
    connections = load_connections()
    idx = next((i for i, c in enumerate(connections) if c.get("id") == conn_id), None)
    if idx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden")
    connections[idx] = connection
    save_connections(connections)
    fire_event("connection.updated", connection)
    return connection


@router.delete("/{conn_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(conn_id: str, current_user: User = Depends(get_current_admin)):
    connections = load_connections()
    deleted = next((c for c in connections if c.get("id") == conn_id), None)
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden")
    save_connections([c for c in connections if c.get("id") != conn_id])
    fire_event("connection.deleted", deleted)


@router.get("/export", response_class=Response)
def export_connections(current_user: User = Depends(get_current_admin)):
    data = json.dumps(load_connections(), ensure_ascii=False, indent=2)
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="connections.json"'},
    )


@router.post("/import")
def import_connections(req: ImportRequest, current_user: User = Depends(get_current_admin)):
    imported = [dict(conn, id=str(uuid.uuid4())) for conn in req.connections]
    if req.mode == "replace":
        save_connections(imported)
    else:
        existing = load_connections()
        existing.extend(imported)
        save_connections(existing)
    fire_event("connections.imported", {"count": len(imported), "mode": req.mode})
    return {"imported": len(imported), "mode": req.mode}
