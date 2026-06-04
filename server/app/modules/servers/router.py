# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.core.config import MONITOR_SERVICE_URL, MONITOR_API_KEY
from app.core.events import fire_event
from app.modules.servers.models import Server
from app.modules.servers.schemas import ServerCreate, ServerUpdate

logger = logging.getLogger("adminhelper.servers")


router = APIRouter(prefix="/api/servers", tags=["servers"])


@router.get("")
def list_servers(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    servers = db.query(Server).order_by(Server.name).all()
    return [s.to_dict() for s in servers]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_server(data: ServerCreate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    server = Server(
        id=str(uuid.uuid4()),
        name=data.name,
        hostname=data.hostname,
        os_type=data.os_type,
        tags=json.dumps(data.tags) if data.tags else None,
        notes=data.notes or "",
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    fire_event("server.created", {"id": server.id, "name": server.name, "hostname": server.hostname})
    return server.to_dict()


@router.get("/{server_id}")
def get_server(server_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server nicht gefunden")
    return server.to_dict()


@router.put("/{server_id}")
def update_server(server_id: str, data: ServerUpdate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server nicht gefunden")

    sent = data.model_fields_set
    for field in ["name", "hostname", "os_type", "notes"]:
        if field in sent:
            setattr(server, field, getattr(data, field))
    if "tags" in sent:
        server.tags = json.dumps(data.tags) if data.tags else None
    db.commit()
    db.refresh(server)
    fire_event("server.updated", {"id": server.id, "name": server.name})
    return server.to_dict()


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server nicht gefunden")
    fire_event("server.deleted", {"id": server.id, "name": server.name})
    db.delete(server)
    db.commit()

    # Monitoring cleanup: delete all checks/alerts/assignments of this server
    try:
        httpx.delete(
            f"{MONITOR_SERVICE_URL}/servers/{server_id}/cleanup",
            headers={"X-Internal-Key": MONITOR_API_KEY},
            timeout=5,
        )
    except Exception as exc:
        logger.warning("Monitoring-Cleanup fuer Server %s fehlgeschlagen: %s", server_id, exc)
