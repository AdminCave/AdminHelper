import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.core.events import fire_event
from app.modules.servers.models import Server
from app.modules.servers.schemas import ServerCreate, ServerUpdate

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
        customer_group_id=data.customer_group_id,
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

    if data.name is not None:
        server.name = data.name
    if data.hostname is not None:
        server.hostname = data.hostname
    if data.os_type is not None:
        server.os_type = data.os_type
    if data.tags is not None:
        server.tags = json.dumps(data.tags) if data.tags else None
    if data.notes is not None:
        server.notes = data.notes
    if data.customer_group_id is not None:
        server.customer_group_id = data.customer_group_id or None

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
