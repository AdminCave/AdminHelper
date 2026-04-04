import json
import secrets
import uuid

import io
import zipfile

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin, ApiKeyOrUser, hash_api_key, generate_api_key
from app.core.config import VISITOR_PORT_START, VISITOR_PORT_END
from app.core.events import fire_event
from app.modules.frp.models import FrpServerConfig, FrpTunnel, ProvisionToken, Visitor, visitor_server_assoc
from app.modules.frp.schemas import (
    FrpServerConfigCreate, FrpServerConfigUpdate,
    FrpTunnelCreate, FrpTunnelUpdate,
    VisitorCreate, VisitorUpdate,
)
from app.modules.connections.models import Connection
from app.modules.frp.config_generator import (
    generate_frps_toml, generate_frpc_toml, generate_visitor_toml,
)
from app.modules.frp.docker_manager import write_frps_config, remove_frps_config
from app.modules.frp import pki as pki_manager
from app.modules.frp import provisioner
from app.modules.servers.models import Server
from app.modules.api_keys.models import ApiKey

router = APIRouter(prefix="/api/frp", tags=["frp"])


def _next_visitor_port(db: Session, exclude_tunnel_id: str | None = None) -> int:
    """Nächsten freien Visitor-Port aus dem konfigurierten Bereich ermitteln."""
    query = db.query(FrpTunnel.visitor_port).filter(
        FrpTunnel.visitor_port.isnot(None),
        FrpTunnel.tunnel_type == "stcp",
    )
    if exclude_tunnel_id:
        query = query.filter(FrpTunnel.id != exclude_tunnel_id)
    used = {row[0] for row in query.all()}
    for port in range(VISITOR_PORT_START, VISITOR_PORT_END + 1):
        if port not in used:
            return port
    raise HTTPException(
        status_code=409,
        detail=f"Keine freien Visitor-Ports im Bereich {VISITOR_PORT_START}–{VISITOR_PORT_END}",
    )


def _get_allow_users(db: Session, server_id: str) -> list[str]:
    """Ermittelt alle Visitor-Usernamen, die Zugriff auf diesen Server haben."""
    visitors = (
        db.query(Visitor)
        .join(visitor_server_assoc, Visitor.id == visitor_server_assoc.c.visitor_id)
        .filter(visitor_server_assoc.c.server_id == server_id)
        .all()
    )
    users = [v.name for v in visitors]
    return users if users else ["ops-admin"]


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
        tls_force=data.tls_force,
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

    sent = data.model_fields_set
    for field in ["name", "server_addr", "bind_port", "vhost_https_port", "auth_token",
                   "subdomain_host", "max_ports_per_client", "dashboard_port",
                   "dashboard_user", "dashboard_password", "tls_force"]:
        if field in sent:
            setattr(config, field, getattr(data, field))

    if "extra_config" in sent:
        config.extra_config = json.dumps(data.extra_config) if data.extra_config else None

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

    visitor_port = data.visitor_port
    if data.tunnel_type == "stcp":
        if not visitor_port:
            visitor_port = _next_visitor_port(db)
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

    # Auto-Connection erstellen wenn gewuenscht
    if data.auto_create_connection:
        auto_conn = None
        if data.tunnel_type == "stcp" and visitor_port:
            conn_kind = "ssh" if data.protocol == "ssh" else "rdp" if data.protocol == "rdp" else "web"
            auto_conn = Connection(
                id=str(uuid.uuid4()),
                name=f"{data.name} (via FRP)",
                kind=conn_kind,
                host="127.0.0.1",
                port=visitor_port,
                server_id=data.server_id,
            )
        elif data.tunnel_type == "https" and data.custom_domains:
            domain = data.custom_domains.split(",")[0].strip()
            if domain:
                auto_conn = Connection(
                    id=str(uuid.uuid4()),
                    name=f"{data.name} (via FRP)",
                    kind="web",
                    url=f"https://{domain}",
                    server_id=data.server_id,
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

    # Name-Unique-Check
    if "name" in sent and data.name != tunnel.name:
        existing = db.query(FrpTunnel).filter(FrpTunnel.name == data.name).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Proxy-Name '{data.name}' existiert bereits")

    # Visitor-Port Duplikat-Prüfung
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

    # STCP ohne Visitor-Port: automatisch zuweisen
    if tunnel.tunnel_type == "stcp" and not tunnel.visitor_port:
        tunnel.visitor_port = _next_visitor_port(db, exclude_tunnel_id=tunnel_id)

    if "extra_config" in sent:
        tunnel.extra_config = json.dumps(data.extra_config) if data.extra_config else None

    if "tags" in sent:
        tunnel.tags = json.dumps(data.tags) if data.tags else None

    # Auto-Connection nachträglich erstellen
    if data.auto_create_connection and not tunnel.connection_id:
        auto_conn = None
        t_type = tunnel.tunnel_type
        if t_type == "stcp" and tunnel.visitor_port:
            conn_kind = "ssh" if tunnel.protocol == "ssh" else "rdp" if tunnel.protocol == "rdp" else "web"
            auto_conn = Connection(
                id=str(uuid.uuid4()),
                name=f"{tunnel.name} (via FRP)",
                kind=conn_kind,
                host="127.0.0.1",
                port=tunnel.visitor_port,
                server_id=tunnel.server_id,
            )
        elif t_type == "https" and tunnel.custom_domains:
            domain = tunnel.custom_domains.split(",")[0].strip()
            if domain:
                auto_conn = Connection(
                    id=str(uuid.uuid4()),
                    name=f"{tunnel.name} (via FRP)",
                    kind="web",
                    url=f"https://{domain}",
                    server_id=tunnel.server_id,
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
        FrpTunnel.enabled.is_(True),
    ).all()
    if not tunnels:
        raise HTTPException(status_code=404, detail="Keine aktiven Tunnel fuer diesen Server")

    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == tunnels[0].frp_config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")

    # frpc_user aus dem ersten Tunnel-Namen ableiten oder Server-Name nutzen
    frpc_user = server.name
    allow_users = _get_allow_users(db, server_id)
    toml = generate_frpc_toml(config, tunnels, frpc_user, allow_users)
    return PlainTextResponse(toml, media_type="application/toml")


@router.get("/generate/visitor-toml")
def gen_visitor_toml(
    config_id: str | None = Query(None),
    visitor_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    if config_id:
        config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    else:
        config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    tunnel_query = db.query(FrpTunnel).filter(
        FrpTunnel.frp_config_id == config.id,
        FrpTunnel.tunnel_type == "stcp",
        FrpTunnel.enabled.is_(True),
    )

    visitor_user = "ops-admin"
    if visitor_id:
        visitor = db.query(Visitor).filter(Visitor.id == visitor_id).first()
        if not visitor:
            raise HTTPException(status_code=404, detail="Visitor nicht gefunden")
        visitor_user = visitor.name
        server_ids = [s.id for s in visitor.servers]
        if server_ids:
            tunnel_query = tunnel_query.filter(FrpTunnel.server_id.in_(server_ids))

    tunnels = tunnel_query.all()
    toml = generate_visitor_toml(config, tunnels, visitor_user)
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
            FrpTunnel.enabled.is_(True),
        ).all()

        by_server = {}
        for t in all_tunnels:
            by_server.setdefault(t.server_id, []).append(t)

        for server_id, tunnels in by_server.items():
            server = db.query(Server).filter(Server.id == server_id).first()
            if not server:
                continue
            allow_users = _get_allow_users(db, server_id)
            frpc = generate_frpc_toml(config, tunnels, server.name, allow_users)
            zf.writestr(f"clients/{server.name}/frpc.toml", frpc)

        # visitor.toml — eine pro Visitor-Profil
        stcp_tunnels = [t for t in all_tunnels if t.tunnel_type == "stcp"]
        visitors = db.query(Visitor).order_by(Visitor.name).all()
        if visitors:
            for visitor in visitors:
                v_server_ids = {s.id for s in visitor.servers}
                v_tunnels = [t for t in stcp_tunnels if t.server_id in v_server_ids]
                if v_tunnels:
                    zf.writestr(f"visitors/visitor-{visitor.name}.toml", generate_visitor_toml(config, v_tunnels, visitor.name))
        else:
            # Fallback: eine globale visitor.toml wenn keine Visitor-Profile existieren
            zf.writestr("visitor.toml", generate_visitor_toml(config, stcp_tunnels))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=frp-configs.zip"},
    )


# --------------- Status Monitoring ---------------

@router.get("/status")
async def frps_status(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    """Fragt den frps-Dashboard-API ab und liefert den Status aller Proxies."""
    import httpx

    config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")
    if not config.dashboard_port:
        raise HTTPException(status_code=400, detail="Dashboard-Port nicht konfiguriert")

    # frps Dashboard ist im Docker-Netzwerk unter dem Service-Namen erreichbar,
    # lokal unter 127.0.0.1
    base_url = f"http://frps:{config.dashboard_port}"
    fallback_url = f"http://127.0.0.1:{config.dashboard_port}"
    auth = (config.dashboard_user or "", config.dashboard_password or "")

    proxies = []
    reachable = False
    async with httpx.AsyncClient(timeout=5.0) as client:
        for proxy_type in ["stcp", "https", "tcp", "udp"]:
            for url in [base_url, fallback_url]:
                try:
                    resp = await client.get(
                        f"{url}/api/proxy/{proxy_type}",
                        auth=auth,
                    )
                    if resp.status_code == 200:
                        reachable = True
                        data = resp.json()
                        for p in data.get("proxies", []):
                            proxies.append({
                                "name": p.get("name", ""),
                                "type": proxy_type,
                                "status": p.get("status", "unknown"),
                                "curConns": p.get("curConns", 0),
                                "clientVersion": p.get("clientVersion", ""),
                                "todayTrafficIn": p.get("todayTrafficIn", 0),
                                "todayTrafficOut": p.get("todayTrafficOut", 0),
                                "lastStartTime": p.get("lastStartTime", ""),
                                "lastCloseTime": p.get("lastCloseTime", ""),
                            })
                        break  # URL funktioniert, keine Fallback noetig
                except Exception:
                    continue  # naechste URL probieren

    if not reachable:
        return {"proxies": [], "total": 0, "error": "frps-Dashboard nicht erreichbar"}

    # Status den lokalen Tunnel-Daten zuordnen
    tunnels = db.query(FrpTunnel).all()
    tunnel_map = {t.name: t.to_dict() for t in tunnels}

    result = []
    for p in proxies:
        # frps Proxy-Name ist "user.proxyName", z.B. "k01-lnx1.k01-lnx1-ssh"
        proxy_name = p["name"].split(".")[-1] if "." in p["name"] else p["name"]
        tunnel = tunnel_map.get(proxy_name)
        result.append({
            **p,
            "tunnel": tunnel,
        })

    return {"proxies": result, "total": len(result)}


# --------------- PKI Management ---------------

@router.get("/pki/status")
def pki_status(_admin=Depends(get_current_admin)):
    return pki_manager.get_pki_status()


@router.post("/pki/ca")
def create_ca(common_name: str = Query("SRM FRP CA"), _admin=Depends(get_current_admin)):
    """Generiert eine neue CA. ACHTUNG: Ueberschreibt bestehende CA!"""
    return pki_manager.generate_ca(common_name)


@router.post("/pki/server-cert")
def create_server_cert(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Generiert ein Server-Zertifikat fuer frps und aktualisiert die Config."""
    status = pki_manager.get_pki_status()
    if not status["caExists"]:
        raise HTTPException(status_code=400, detail="Zuerst eine CA generieren")

    config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    result = pki_manager.generate_server_cert(config.server_addr)

    # Pfade in der Config speichern
    config.tls_cert_file = result["certPath"]
    config.tls_key_file = result["keyPath"]
    config.tls_ca_file = str(pki_manager.PKI_DIR / "ca.crt")
    db.commit()
    db.refresh(config)
    write_frps_config(config)

    return result


@router.post("/pki/client-cert/{client_name}")
def create_client_cert(client_name: str, _admin=Depends(get_current_admin)):
    """Generiert ein Client-Zertifikat fuer einen frpc-Host."""
    status = pki_manager.get_pki_status()
    if not status["caExists"]:
        raise HTTPException(status_code=400, detail="Zuerst eine CA generieren")
    return pki_manager.generate_client_cert(client_name)


@router.get("/pki/download/{filename}")
def download_pki_file(filename: str, _admin=Depends(get_current_admin)):
    """Laed eine PKI-Datei herunter (.crt oder .key)."""
    # Nur .crt und .key erlauben, Path-Traversal verhindern
    safe_name = Path(filename).name
    if not safe_name.endswith((".crt", ".key")):
        raise HTTPException(status_code=400, detail="Nur .crt und .key Dateien erlaubt")
    file_path = pki_manager.PKI_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Datei '{safe_name}' nicht gefunden")
    media = "application/x-pem-file"
    return FileResponse(file_path, filename=safe_name, media_type=media)


@router.get("/pki/download-client-bundle/{client_name}")
def download_client_bundle(client_name: str, _admin=Depends(get_current_admin)):
    """Laed ein ZIP mit ca.crt, client.crt und client.key herunter."""
    safe_name = Path(client_name).name
    d = pki_manager.PKI_DIR
    ca_crt = d / "ca.crt"
    client_crt = d / f"{safe_name}.crt"
    client_key = d / f"{safe_name}.key"

    for f in [ca_crt, client_crt, client_key]:
        if not f.exists():
            raise HTTPException(status_code=404, detail=f"Datei '{f.name}' nicht gefunden")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ca_crt, "pki/ca.crt")
        zf.write(client_crt, f"pki/{safe_name}.crt")
        zf.write(client_key, f"pki/{safe_name}.key")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-pki.zip"'},
    )


# --------------- Visitors ---------------

@router.get("/visitors")
def list_visitors(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    visitors = db.query(Visitor).order_by(Visitor.name).all()
    return [v.to_dict() for v in visitors]


@router.post("/visitors", status_code=status.HTTP_201_CREATED)
def create_visitor(data: VisitorCreate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    existing = db.query(Visitor).filter(Visitor.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Visitor-Name '{data.name}' existiert bereits")

    visitor = Visitor(
        id=str(uuid.uuid4()),
        name=data.name,
        display_name=data.display_name,
        notes=data.notes,
    )

    # Server zuweisen
    if data.server_ids:
        servers = db.query(Server).filter(Server.id.in_(data.server_ids)).all()
        visitor.servers = servers

    db.add(visitor)
    db.commit()
    db.refresh(visitor)
    return visitor.to_dict()


@router.put("/visitors/{visitor_id}")
def update_visitor(visitor_id: str, data: VisitorUpdate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    visitor = db.query(Visitor).filter(Visitor.id == visitor_id).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor nicht gefunden")

    if data.name is not None and data.name != visitor.name:
        existing = db.query(Visitor).filter(Visitor.name == data.name).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Visitor-Name '{data.name}' existiert bereits")
        visitor.name = data.name

    if data.display_name is not None:
        visitor.display_name = data.display_name
    if data.notes is not None:
        visitor.notes = data.notes
    if data.server_ids is not None:
        servers = db.query(Server).filter(Server.id.in_(data.server_ids)).all()
        visitor.servers = servers

    db.commit()
    db.refresh(visitor)
    return visitor.to_dict()


@router.delete("/visitors/{visitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_visitor(visitor_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    visitor = db.query(Visitor).filter(Visitor.id == visitor_id).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor nicht gefunden")
    db.delete(visitor)
    db.commit()


# --------------- Provisioning ---------------

read_dep = ApiKeyOrUser(require_write=False)


@router.post("/provision/{server_id}/token")
def create_provision_token(
    server_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Erstellt einen einmaligen Provision-Token fuer einen Server (24h gueltig)."""
    import datetime

    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    raw_token = f"srm_prov_{secrets.token_urlsafe(32)}"
    hashed = hash_api_key(raw_token)

    token = ProvisionToken(
        id=str(uuid.uuid4()),
        server_id=server_id,
        hashed_token=hashed,
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
    )
    db.add(token)
    db.commit()
    db.refresh(token)

    return {
        "token": raw_token,
        "expiresAt": token.expires_at.isoformat(),
        "serverId": server_id,
        "serverName": server.name,
    }


@router.get("/provision/{server_id}/tokens")
def list_provision_tokens(
    server_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Listet alle Provision-Tokens fuer einen Server auf."""
    tokens = db.query(ProvisionToken).filter(
        ProvisionToken.server_id == server_id
    ).order_by(ProvisionToken.created_at.desc()).all()
    return [t.to_dict() for t in tokens]


@router.post("/provision/{server_id}/activate")
def activate_provision(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Loest einen Provision-Token ein und liefert API-Key + Config + PKI."""
    import base64
    import datetime

    raw_token = request.headers.get("X-Provision-Token", "")
    if not raw_token:
        raise HTTPException(status_code=401, detail="X-Provision-Token Header fehlt")

    hashed = hash_api_key(raw_token)
    token = db.query(ProvisionToken).filter(ProvisionToken.hashed_token == hashed).first()
    if not token:
        raise HTTPException(status_code=401, detail="Ungueltiger Provision-Token")
    if not token.is_valid():
        raise HTTPException(status_code=401, detail="Token abgelaufen oder bereits verwendet")
    if token.server_id != server_id:
        raise HTTPException(status_code=403, detail="Token gehoert nicht zu diesem Server")

    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    # Token als verwendet markieren
    token.used_at = datetime.datetime.now(datetime.timezone.utc)

    # Read-only API-Key erstellen
    raw_api_key = generate_api_key()
    api_key = ApiKey(
        name=f"frpc-sync-{server.name}",
        hashed_key=hash_api_key(raw_api_key),
        permission="read",
    )
    db.add(api_key)

    # Client-Cert generieren falls noetig
    pki_status = pki_manager.get_pki_status()
    if pki_status["caExists"]:
        client_crt = pki_manager.PKI_DIR / f"{server.name}.crt"
        if not client_crt.exists():
            pki_manager.generate_client_cert(server.name)

    db.commit()

    # frpc.toml generieren
    tunnels = db.query(FrpTunnel).filter(
        FrpTunnel.server_id == server_id,
        FrpTunnel.frp_config_id == config.id,
    ).all()
    allow_users = _get_allow_users(db, server_id)
    frpc_toml = generate_frpc_toml(config, tunnels, server.name, allow_users)

    # PKI Bundle
    pki_bundle = provisioner.build_pki_bundle_b64(server.name)

    return {
        "apiKey": raw_api_key,
        "config": base64.b64encode(frpc_toml.encode()).decode(),
        "pkiBundle": pki_bundle or "",
        "serverName": server.name,
    }


@router.get("/provision/{server_id}/config")
def get_provision_config(
    server_id: str,
    db: Session = Depends(get_db),
    auth=Depends(read_dep),
):
    """Liefert die aktuelle frpc.toml fuer den Sync-Agent."""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    tunnels = db.query(FrpTunnel).filter(
        FrpTunnel.server_id == server_id,
        FrpTunnel.frp_config_id == config.id,
    ).all()

    allow_users = _get_allow_users(db, server_id)
    toml_content = generate_frpc_toml(config, tunnels, server.name, allow_users)
    return PlainTextResponse(toml_content, media_type="application/toml")


@router.get("/provision/{server_id}/config-hash")
def get_provision_config_hash(
    server_id: str,
    db: Session = Depends(get_db),
    auth=Depends(read_dep),
):
    """Liefert den SHA256-Hash der aktuellen frpc.toml."""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    tunnels = db.query(FrpTunnel).filter(
        FrpTunnel.server_id == server_id,
        FrpTunnel.frp_config_id == config.id,
    ).all()

    allow_users = _get_allow_users(db, server_id)
    config_hash = provisioner.get_config_hash(config, tunnels, server.name, allow_users=allow_users)
    return {"hash": config_hash}
