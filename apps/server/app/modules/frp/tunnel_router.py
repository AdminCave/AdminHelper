# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin, get_current_user
from app.core.database import get_db
from app.core.events import fire_event
from app.core.request_context import actor_from_request
from app.modules.audit import service as audit
from app.modules.connections.models import Connection
from app.modules.frp._helpers import create_auto_connection, next_visitor_port
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.schemas import (
    PORT_MAX,
    PORT_MIN,
    FrpTunnelCreate,
    FrpTunnelOut,
    FrpTunnelUpdate,
    TunnelListItem,
)
from app.modules.servers.models import Server

router = APIRouter(prefix="/api/frp", tags=["frp"])

# The keys of a tunnel a non-admin reads: what the desktop deserialises it into (TunnelMapping in
# apps/desktop/src-tauri/src/tunnel.rs, pinned by tests/test_frp_tunnel_access.py).
_MAPPING_FIELDS = (
    "id",
    "serverId",
    "tunnelType",
    "protocol",
    "localPort",
    "visitorPort",
    "customDomains",
    "connectionId",
    "enabled",
    "name",
)


@router.get("/tunnels", response_model=list[TunnelListItem])
def list_tunnels(
    server_id: str | None = Query(None),
    frp_config_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(FrpTunnel)
    if not current_user.is_admin:
        # The desktop resolves a non-admin's connections through these mappings, so he reads the
        # enabled tunnels of his assigned servers, nothing beyond TunnelMapping: the same split as
        # _visible_stcp_tunnels. The query parameters below only narrow this further.
        server_ids = [s.id for s in current_user.servers]
        if not server_ids:
            return []
        query = query.filter(FrpTunnel.server_id.in_(server_ids), FrpTunnel.enabled.is_(True))
    if server_id:
        query = query.filter(FrpTunnel.server_id == server_id)
    if frp_config_id:
        query = query.filter(FrpTunnel.frp_config_id == frp_config_id)
    listed = [t.to_dict(mask_secrets=True) for t in query.order_by(FrpTunnel.name).all()]
    if current_user.is_admin:
        return listed
    return [{key: t[key] for key in _MAPPING_FIELDS} for t in listed]


def _port_taken(db: Session, port: int, tunnel_id: str) -> bool:
    """Whether another stcp tunnel already binds this visitor port."""
    return (
        db.query(FrpTunnel.id)
        .filter(
            FrpTunnel.visitor_port == port,
            FrpTunnel.tunnel_type == "stcp",
            FrpTunnel.id != tunnel_id,
        )
        .first()
        is not None
    )


def _reject_bad_local_port(value: int | None) -> None:
    """frpc refuses the whole config of a host for a localPort outside 0-65535, and 0 is no
    target. Checked here, not in the schema, so the published OpenAPI contract stays as it is;
    RequestValidationError keeps the 422 in the declared shape."""
    if value is not None and PORT_MIN <= value <= PORT_MAX:
        return
    raise RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "local_port"),
                "msg": "local_port must be a port from 1 to 65535",
                "input": value,
            }
        ]
    )


def _reject_unknown_connection(db: Session, connection_id: str | None) -> None:
    """A connection_id no row matches reached the INSERT and failed on its foreign key.
    RequestValidationError, not HTTPException, so the 422 keeps the shape the OpenAPI
    schema declares (as _reject_unknown_server in connections/router.py)."""
    if connection_id is None:
        return
    if db.query(Connection.id).filter(Connection.id == connection_id).first() is None:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "connection_id"),
                    "msg": "connection not found",
                    "input": connection_id,
                }
            ]
        )


def _attach_auto_connection(db: Session, tunnel: FrpTunnel, username: str | None) -> None:
    """Create the paired auto-connection for a tunnel (if the checker returns one)
    and link it back. Shared by create_tunnel and update_tunnel so the args — esp.
    the JSON-encoded tags — and the linking stay identical (2.47)."""
    auto_conn = create_auto_connection(tunnel, username=username)
    if auto_conn:
        db.add(auto_conn)
        db.flush()
        tunnel.connection_id = auto_conn.id


@router.post("/tunnels", status_code=status.HTTP_201_CREATED, response_model=FrpTunnelOut)
def create_tunnel(
    data: FrpTunnelCreate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    _reject_bad_local_port(data.local_port)
    server = db.query(Server).filter(Server.id == data.server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == data.frp_config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")
    _reject_unknown_connection(db, data.connection_id)

    existing = db.query(FrpTunnel).filter(FrpTunnel.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Proxy-Name '{data.name}' existiert bereits")

    # secret_key and visitor_port belong to stcp; any other type stores neither.
    is_stcp = data.tunnel_type == "stcp"
    secret = data.secret_key if is_stcp else None
    if is_stcp and not secret:
        secret = FrpTunnel.generate_secret()

    visitor_port = data.visitor_port if is_stcp else None
    if is_stcp:
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
    try:
        db.flush()
        if data.auto_create_connection:
            _attach_auto_connection(db, tunnel, data.auto_connection_username)
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
    return tunnel.to_dict(mask_secrets=True)


@router.get("/tunnels/{tunnel_id}", response_model=FrpTunnelOut)
def get_tunnel(tunnel_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    tunnel = db.query(FrpTunnel).filter(FrpTunnel.id == tunnel_id).first()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel nicht gefunden")
    return tunnel.to_dict(mask_secrets=True)


@router.put("/tunnels/{tunnel_id}", response_model=FrpTunnelOut)
def update_tunnel(
    tunnel_id: str,
    data: FrpTunnelUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    sent = data.model_fields_set
    if "local_port" in sent:
        _reject_bad_local_port(data.local_port)
    tunnel = db.query(FrpTunnel).filter(FrpTunnel.id == tunnel_id).first()
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel nicht gefunden")

    if "connection_id" in sent:
        _reject_unknown_connection(db, data.connection_id)
    # Responses never carry the secret, so an editor sends the field back
    # empty: on update, null or "" means "keep the stored secret".
    if "secret_key" in sent and not data.secret_key:
        sent = sent - {"secret_key"}

    if "name" in sent and data.name != tunnel.name:
        existing = db.query(FrpTunnel).filter(FrpTunnel.name == data.name).first()
        if existing:
            raise HTTPException(
                status_code=409, detail=f"Proxy-Name '{data.name}' existiert bereits"
            )

    was_stcp = tunnel.tunnel_type == "stcp"
    ends_stcp = (data.tunnel_type if "tunnel_type" in sent else tunnel.tunnel_type) == "stcp"

    if ends_stcp and "visitor_port" in sent and data.visitor_port:
        if _port_taken(db, data.visitor_port, tunnel_id):
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

    if not ends_stcp:
        # An https tunnel keeps no stcp fields: its port is free for another stcp tunnel,
        # and a later switch back starts with a new secret.
        tunnel.secret_key = None
        tunnel.visitor_port = None
    else:
        if not was_stcp and "secret_key" not in sent:
            tunnel.secret_key = None  # a switch to stcp always gets a new secret
        if (
            tunnel.visitor_port
            and "visitor_port" not in sent
            and (
                not PORT_MIN <= tunnel.visitor_port <= PORT_MAX
                or _port_taken(db, tunnel.visitor_port, tunnel_id)
            )
        ):
            # A stored port another stcp tunnel took meanwhile (rows from before https
            # cleared it) is replaced, and so is one outside 1-65535 stored before R-0533:
            # the auto-connection would point at it, and no visitor ever binds it. Only a
            # port the client sends is a 409 (or a 422 from the schema).
            tunnel.visitor_port = None
        if not tunnel.visitor_port:
            tunnel.visitor_port = next_visitor_port(db, exclude_tunnel_id=tunnel_id)
        if not tunnel.secret_key:
            tunnel.secret_key = FrpTunnel.generate_secret()

    if "extra_config" in sent:
        tunnel.extra_config = json.dumps(data.extra_config) if data.extra_config else None

    if "tags" in sent:
        tunnel.tags = json.dumps(data.tags) if data.tags else None

    try:
        if data.auto_create_connection and not tunnel.connection_id:
            _attach_auto_connection(db, tunnel, data.auto_connection_username)
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
    return tunnel.to_dict(mask_secrets=True)


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
