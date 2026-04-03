import json
import secrets
import uuid

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.core.events import fire_event
from app.modules.frp.models import FrpServerConfig, FrpTunnel, CustomerGroup
from app.modules.frp.schemas import (
    FrpServerConfigCreate, FrpServerConfigUpdate,
    FrpTunnelCreate, FrpTunnelUpdate,
    CustomerGroupCreate, CustomerGroupUpdate,
)
from app.modules.connections.models import Connection
from app.modules.frp.config_generator import (
    generate_frps_toml, generate_frpc_toml, generate_visitor_toml,
)
from app.modules.frp.docker_manager import write_frps_config, remove_frps_config
from app.modules.servers.models import Server

router = APIRouter(prefix="/api/frp", tags=["frp"])


# --------------- FRP Server Config ---------------

@router.get("/server-config")
def list_server_configs(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    configs = db.query(FrpServerConfig).all()
    return [c.to_dict() for c in configs]


@router.post("/server-config", status_code=status.HTTP_201_CREATED)
def create_server_config(data: FrpServerConfigCreate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    config = FrpServerConfig(
        id=str(uuid.uuid4()),
        name=data.name,
        server_addr=data.server_addr,
        bind_port=data.bind_port,
        vhost_https_port=data.vhost_https_port,
        auth_token=data.auth_token or secrets.token_urlsafe(32),
        subdomain_host=data.subdomain_host,
        max_ports_per_client=data.max_ports_per_client,
        dashboard_port=data.dashboard_port,
        dashboard_user=data.dashboard_user,
        dashboard_password=data.dashboard_password,
        extra_config=json.dumps(data.extra_config) if data.extra_config else None,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    write_frps_config(config)
    fire_event("frp.config.created", {"id": config.id, "name": config.name})
    return config.to_dict()


@router.get("/server-config/{config_id}")
def get_server_config(config_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")
    return config.to_dict(include_tunnels=True)


@router.put("/server-config/{config_id}")
def update_server_config(config_id: str, data: FrpServerConfigUpdate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")

    for field in ["name", "server_addr", "bind_port", "vhost_https_port", "auth_token",
                   "subdomain_host", "max_ports_per_client", "dashboard_port",
                   "dashboard_user", "dashboard_password"]:
        value = getattr(data, field)
        if value is not None:
            setattr(config, field, value)

    if data.extra_config is not None:
        config.extra_config = json.dumps(data.extra_config)

    db.commit()
    db.refresh(config)
    write_frps_config(config)
    fire_event("frp.config.updated", {"id": config.id, "name": config.name})
    return config.to_dict()


@router.delete("/server-config/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server_config(config_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")
    fire_event("frp.config.deleted", {"id": config.id, "name": config.name})
    db.delete(config)
    db.commit()
    remove_frps_config()


# --------------- FRP Tunnels ---------------

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
    # Validierungen
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

    # STCP braucht secret_key und visitor_port
    secret = data.secret_key
    if data.tunnel_type == "stcp" and not secret:
        secret = FrpTunnel.generate_secret()

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
        visitor_port=data.visitor_port,
        connection_id=data.connection_id,
        enabled=data.enabled,
        extra_config=json.dumps(data.extra_config) if data.extra_config else None,
    )
    db.add(tunnel)
    db.flush()

    # Auto-Connection erstellen wenn gewuenscht
    if data.auto_create_connection and data.tunnel_type == "stcp" and data.visitor_port:
        conn_kind = "ssh" if data.protocol == "ssh" else "rdp" if data.protocol == "rdp" else "web"
        auto_conn = Connection(
            id=str(uuid.uuid4()),
            name=f"{data.name} (via FRP)",
            kind=conn_kind,
            host="127.0.0.1",
            port=data.visitor_port,
            server_id=data.server_id,
        )
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

    # Name-Unique-Check
    if data.name is not None and data.name != tunnel.name:
        existing = db.query(FrpTunnel).filter(FrpTunnel.name == data.name).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Proxy-Name '{data.name}' existiert bereits")

    for field in ["name", "tunnel_type", "protocol", "local_ip", "local_port",
                   "secret_key", "custom_domains", "visitor_port", "connection_id", "enabled"]:
        value = getattr(data, field)
        if value is not None:
            setattr(tunnel, field, value)

    if data.extra_config is not None:
        tunnel.extra_config = json.dumps(data.extra_config)

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


# --------------- Config-Generierung ---------------

@router.get("/generate/frps-toml")
def gen_frps_toml(
    config_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    if config_id:
        config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    else:
        config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")
    toml = generate_frps_toml(config)
    return PlainTextResponse(toml, media_type="application/toml")


@router.get("/generate/frpc-toml/{server_id}")
def gen_frpc_toml(server_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    tunnels = db.query(FrpTunnel).filter(
        FrpTunnel.server_id == server_id,
        FrpTunnel.enabled == True,
    ).all()
    if not tunnels:
        raise HTTPException(status_code=404, detail="Keine aktiven Tunnel fuer diesen Server")

    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == tunnels[0].frp_config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")

    # frpc_user aus dem ersten Tunnel-Namen ableiten oder Server-Name nutzen
    frpc_user = server.name
    toml = generate_frpc_toml(config, tunnels, frpc_user)
    return PlainTextResponse(toml, media_type="application/toml")


@router.get("/generate/visitor-toml")
def gen_visitor_toml(
    config_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    if config_id:
        config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    else:
        config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    tunnels = db.query(FrpTunnel).filter(
        FrpTunnel.frp_config_id == config.id,
        FrpTunnel.tunnel_type == "stcp",
        FrpTunnel.enabled == True,
    ).all()

    toml = generate_visitor_toml(config, tunnels)
    return PlainTextResponse(toml, media_type="application/toml")


@router.get("/generate/bulk-zip")
def gen_bulk_zip(
    config_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Generiert ein ZIP mit frps.toml, visitor.toml und frpc.toml pro Server."""
    if config_id:
        config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    else:
        config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # frps.toml
        zf.writestr("frps.toml", generate_frps_toml(config))

        # Alle Tunnel nach Server gruppieren
        all_tunnels = db.query(FrpTunnel).filter(
            FrpTunnel.frp_config_id == config.id,
            FrpTunnel.enabled == True,
        ).all()

        by_server = {}
        for t in all_tunnels:
            by_server.setdefault(t.server_id, []).append(t)

        for server_id, tunnels in by_server.items():
            server = db.query(Server).filter(Server.id == server_id).first()
            if not server:
                continue
            frpc = generate_frpc_toml(config, tunnels, server.name)
            zf.writestr(f"clients/{server.name}/frpc.toml", frpc)

        # visitor.toml
        stcp_tunnels = [t for t in all_tunnels if t.tunnel_type == "stcp"]
        zf.writestr("visitor.toml", generate_visitor_toml(config, stcp_tunnels))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=frp-configs.zip"},
    )


# --------------- Customer Groups ---------------

@router.get("/customer-groups")
def list_customer_groups(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    groups = db.query(CustomerGroup).order_by(CustomerGroup.prefix).all()
    return [g.to_dict() for g in groups]


@router.post("/customer-groups", status_code=status.HTTP_201_CREATED)
def create_customer_group(data: CustomerGroupCreate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    existing = db.query(CustomerGroup).filter(CustomerGroup.prefix == data.prefix).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Prefix '{data.prefix}' existiert bereits")

    group = CustomerGroup(
        id=str(uuid.uuid4()),
        prefix=data.prefix,
        name=data.name,
        port_range_start=data.port_range_start,
        notes=data.notes,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group.to_dict()


@router.get("/customer-groups/{group_id}")
def get_customer_group(group_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    group = db.query(CustomerGroup).filter(CustomerGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Kundengruppe nicht gefunden")
    return group.to_dict(include_servers=True)


@router.put("/customer-groups/{group_id}")
def update_customer_group(group_id: str, data: CustomerGroupUpdate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    group = db.query(CustomerGroup).filter(CustomerGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Kundengruppe nicht gefunden")

    if data.prefix is not None and data.prefix != group.prefix:
        existing = db.query(CustomerGroup).filter(CustomerGroup.prefix == data.prefix).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Prefix '{data.prefix}' existiert bereits")

    for field in ["prefix", "name", "port_range_start", "notes"]:
        value = getattr(data, field)
        if value is not None:
            setattr(group, field, value)

    db.commit()
    db.refresh(group)
    return group.to_dict()


@router.delete("/customer-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer_group(group_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    group = db.query(CustomerGroup).filter(CustomerGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Kundengruppe nicht gefunden")
    db.delete(group)
    db.commit()


@router.get("/customer-groups/{group_id}/next-port")
def get_next_visitor_port(group_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    """Gibt den naechsten freien Visitor-Port fuer diese Kundengruppe zurueck."""
    group = db.query(CustomerGroup).filter(CustomerGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Kundengruppe nicht gefunden")

    # Alle Tunnel der Server in dieser Gruppe sammeln
    server_ids = [s.id for s in group.servers]
    tunnels = db.query(FrpTunnel).filter(FrpTunnel.server_id.in_(server_ids)).all() if server_ids else []
    return {"nextPort": group.next_visitor_port(tunnels)}
