# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin
from app.core.database import get_db
from app.core.events import fire_event
from app.core.request_context import actor_from_request
from app.modules.audit import service as audit
from app.modules.frp._helpers import create_auto_connection, next_visitor_port
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.schemas import FrpTunnelCreate, FrpTunnelUpdate
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


def _attach_auto_connection(db: Session, tunnel: FrpTunnel, username: str | None) -> None:
    """Create the paired auto-connection for a tunnel (if the checker returns one)
    and link it back. Shared by create_tunnel and update_tunnel so the args — esp.
    the JSON-encoded tags — and the linking stay identical (2.47)."""
    auto_conn = create_auto_connection(
        tunnel.name,
        tunnel.tunnel_type,
        tunnel.protocol,
        tunnel.custom_domains,
        tunnel.visitor_port,
        tunnel.server_id,
        db,
        tags=tunnel.tags,
        username=username,
    )
    if auto_conn:
        db.add(auto_conn)
        db.flush()
        tunnel.connection_id = auto_conn.id


@router.post("/tunnels", status_code=status.HTTP_201_CREATED)
def create_tunnel(
    data: FrpTunnelCreate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    server = db.query(Server).filter(Server.id == data.server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == data.frp_config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")

    existing = db.query(FrpTunnel).filter(FrpTunnel.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Proxy-Name '{data.name}' existiert bereits")

    secret = data.secret_key
    if data.tunnel_type == "stcp" and not secret:
        secret = FrpTunnel.generate_secret()

    visitor_port = data.visitor_port
    if data.tunnel_type == "stcp":
        if not visitor_port:
            visitor_port = next_visitor_port(db)
        else:
            conflict = (
                db.query(FrpTunnel)
                .filter(FrpTunnel.visitor_port == visitor_port, FrpTunnel.tunnel_type == "stcp")
                .first()
            )
            if conflict:
                raise HTTPException(
                    status_code=409, detail=f"Visitor-Port {visitor_port} ist bereits belegt"
                )

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
        _attach_auto_connection(db, tunnel, data.auto_connection_username)

    try:
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent create on the same proxy name or
        # STCP visitor_port (the read-then-check above has a TOCTOU window; the
        # DB constraints are the only race-free guard). Map to the same 409.
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Proxy-Name oder Visitor-Port ist bereits belegt"
        )
    db.refresh(tunnel)
    fire_event("frp.tunnel.created", {"id": tunnel.id, "name": tunnel.name, "serverId": server.id})
    audit.record(
        db,
        "frp.tunnel.created",
        actor=actor_from_request(request),
        object_type="frp_tunnel",
        object_id=tunnel.id,
        object_label=tunnel.name,
    )
    return tunnel.to_dict()


@router.get("/tunnels/{tunnel_id}")
def get_tunnel(tunnel_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    tunnel = db.query(FrpTunnel).filter(FrpTunnel.id == tunnel_id).first()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel nicht gefunden")
    return tunnel.to_dict()


@router.put("/tunnels/{tunnel_id}")
def update_tunnel(
    tunnel_id: str,
    data: FrpTunnelUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    tunnel = db.query(FrpTunnel).filter(FrpTunnel.id == tunnel_id).first()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel nicht gefunden")

    sent = data.model_fields_set

    if "name" in sent and data.name != tunnel.name:
        existing = db.query(FrpTunnel).filter(FrpTunnel.name == data.name).first()
        if existing:
            raise HTTPException(
                status_code=409, detail=f"Proxy-Name '{data.name}' existiert bereits"
            )

    if "visitor_port" in sent and data.visitor_port:
        conflict = (
            db.query(FrpTunnel)
            .filter(
                FrpTunnel.visitor_port == data.visitor_port,
                FrpTunnel.tunnel_type == "stcp",
                FrpTunnel.id != tunnel_id,
            )
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=409, detail=f"Visitor-Port {data.visitor_port} ist bereits belegt"
            )

    for field in [
        "name",
        "tunnel_type",
        "protocol",
        "local_ip",
        "local_port",
        "secret_key",
        "custom_domains",
        "visitor_port",
        "connection_id",
        "enabled",
    ]:
        if field in sent:
            setattr(tunnel, field, getattr(data, field))

    if tunnel.tunnel_type == "stcp" and not tunnel.visitor_port:
        tunnel.visitor_port = next_visitor_port(db, exclude_tunnel_id=tunnel_id)

    if "extra_config" in sent:
        tunnel.extra_config = json.dumps(data.extra_config) if data.extra_config else None

    if "tags" in sent:
        tunnel.tags = json.dumps(data.tags) if data.tags else None

    if data.auto_create_connection and not tunnel.connection_id:
        _attach_auto_connection(db, tunnel, data.auto_connection_username)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Proxy-Name oder Visitor-Port ist bereits belegt"
        )
    db.refresh(tunnel)
    fire_event("frp.tunnel.updated", {"id": tunnel.id, "name": tunnel.name})
    audit.record(
        db,
        "frp.tunnel.updated",
        actor=actor_from_request(request),
        object_type="frp_tunnel",
        object_id=tunnel.id,
        object_label=tunnel.name,
    )
    return tunnel.to_dict()


@router.delete("/tunnels/{tunnel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tunnel(
    tunnel_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    tunnel = db.query(FrpTunnel).filter(FrpTunnel.id == tunnel_id).first()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel nicht gefunden")
    tunnel_name = tunnel.name
    db.delete(tunnel)
    db.commit()
    # Fire only after the commit succeeds — a rolled-back delete must not leave
    # hooks/notifications having observed a deletion that never happened (2.48).
    fire_event("frp.tunnel.deleted", {"id": tunnel_id, "name": tunnel_name})
    audit.record(
        db,
        "frp.tunnel.deleted",
        actor=actor_from_request(request),
        object_type="frp_tunnel",
        object_id=tunnel_id,
        object_label=tunnel_name,
    )
