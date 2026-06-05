# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.core.events import fire_event
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.schemas import FrpTunnelCreate, FrpTunnelUpdate
from app.modules.frp._helpers import create_auto_connection, next_visitor_port
from app.modules.servers.models import Server

router = APIRouter(prefix="/api/frp", tags=["frp"])


@router.get("/tunnels")
def list_tunnels(
    server_id: str | None = Query(None),
    frp_config_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    query = db.query(FrpTunnel)
    if server_id:
        query = query.filter(FrpTunnel.server_id == server_id)
    if frp_config_id:
        query = query.filter(FrpTunnel.frp_config_id == frp_config_id)
    tunnels = query.order_by(FrpTunnel.name).all()
    return [t.to_dict() for t in tunnels]


@router.post("/tunnels", status_code=status.HTTP_201_CREATED)
def create_tunnel(data: FrpTunnelCreate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    server = db.query(Server).filter(Server.id == data.server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == data.frp_config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")

    existing = db.query(FrpTunnel).filter(FrpTunnel.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Proxy-Name '{data.name}' existiert bereits")

    if data.tunnel_type not in ("stcp", "https"):
        raise HTTPException(status_code=400, detail="tunnel_type muss 'stcp' oder 'https' sein")

    secret = data.secret_key
    if data.tunnel_type == "stcp" and not secret:
        secret = FrpTunnel.generate_secret()

    visitor_port = data.visitor_port
    if data.tunnel_type == "stcp":
        if not visitor_port:
            visitor_port = next_visitor_port(db)
        else:
            conflict = db.query(FrpTunnel).filter(
                FrpTunnel.visitor_port == visitor_port, FrpTunnel.tunnel_type == "stcp"
            ).first()
            if conflict:
                raise HTTPException(status_code=409, detail=f"Visitor-Port {visitor_port} ist bereits belegt")

    tunnel = FrpTunnel(
        id=str(uuid.uuid4()),
        server_id=data.server_id,
        frp_config_id=data.frp_config_id,
        name=data.name,
        tunnel_type=data.tunnel_type,
        protocol=data.protocol,
        local_ip=data.local_ip,
        local_port=data.local_port,
        secret_key=secret,
        custom_domains=data.custom_domains,
        visitor_port=visitor_port,
        connection_id=data.connection_id,
        enabled=data.enabled,
        extra_config=json.dumps(data.extra_config) if data.extra_config else None,
        tags=json.dumps(data.tags) if data.tags else None,
    )
    db.add(tunnel)
    db.flush()

    if data.auto_create_connection:
        auto_conn = create_auto_connection(
            data.name, data.tunnel_type, data.protocol,
            data.custom_domains, visitor_port, data.server_id, db,
            tags=json.dumps(data.tags) if data.tags else None,
            username=data.auto_connection_username,
        )
        if auto_conn:
            db.add(auto_conn)
            db.flush()
            tunnel.connection_id = auto_conn.id

    db.commit()
    db.refresh(tunnel)
    fire_event("frp.tunnel.created", {"id": tunnel.id, "name": tunnel.name, "serverId": server.id})
    return tunnel.to_dict()


@router.get("/tunnels/{tunnel_id}")
def get_tunnel(tunnel_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    tunnel = db.query(FrpTunnel).filter(FrpTunnel.id == tunnel_id).first()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel nicht gefunden")
    return tunnel.to_dict()


@router.put("/tunnels/{tunnel_id}")
def update_tunnel(tunnel_id: str, data: FrpTunnelUpdate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    tunnel = db.query(FrpTunnel).filter(FrpTunnel.id == tunnel_id).first()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel nicht gefunden")

    sent = data.model_fields_set

    if "name" in sent and data.name != tunnel.name:
        existing = db.query(FrpTunnel).filter(FrpTunnel.name == data.name).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Proxy-Name '{data.name}' existiert bereits")

    if "visitor_port" in sent and data.visitor_port:
        conflict = db.query(FrpTunnel).filter(
            FrpTunnel.visitor_port == data.visitor_port,
            FrpTunnel.tunnel_type == "stcp",
            FrpTunnel.id != tunnel_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail=f"Visitor-Port {data.visitor_port} ist bereits belegt")

    for field in ["name", "tunnel_type", "protocol", "local_ip", "local_port",
                   "secret_key", "custom_domains", "visitor_port", "connection_id", "enabled"]:
        if field in sent:
            setattr(tunnel, field, getattr(data, field))

    if tunnel.tunnel_type == "stcp" and not tunnel.visitor_port:
        tunnel.visitor_port = next_visitor_port(db, exclude_tunnel_id=tunnel_id)

    if "extra_config" in sent:
        tunnel.extra_config = json.dumps(data.extra_config) if data.extra_config else None

    if "tags" in sent:
        tunnel.tags = json.dumps(data.tags) if data.tags else None

    if data.auto_create_connection and not tunnel.connection_id:
        auto_conn = create_auto_connection(
            tunnel.name, tunnel.tunnel_type, tunnel.protocol,
            tunnel.custom_domains, tunnel.visitor_port, tunnel.server_id, db,
            tags=tunnel.tags,
            username=data.auto_connection_username,
        )
        if auto_conn:
            db.add(auto_conn)
            db.flush()
            tunnel.connection_id = auto_conn.id

    db.commit()
    db.refresh(tunnel)
    fire_event("frp.tunnel.updated", {"id": tunnel.id, "name": tunnel.name})
    return tunnel.to_dict()


@router.delete("/tunnels/{tunnel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tunnel(tunnel_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    tunnel = db.query(FrpTunnel).filter(FrpTunnel.id == tunnel_id).first()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel nicht gefunden")
    fire_event("frp.tunnel.deleted", {"id": tunnel.id, "name": tunnel.name})
    db.delete(tunnel)
    db.commit()
