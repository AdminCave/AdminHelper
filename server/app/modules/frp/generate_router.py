# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin, get_current_user
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp._helpers import get_allow_users
from app.modules.frp.config_generator import generate_frps_toml, generate_frpc_toml, generate_visitor_toml
from app.modules.frp import pki as pki_manager
from app.modules.users.models import User
from app.modules.servers.models import Server

router = APIRouter(prefix="/api/frp", tags=["frp"])


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

    frpc_user = server.name
    allow_users = get_allow_users(db, server_id)
    toml = generate_frpc_toml(config, tunnels, frpc_user, allow_users)
    return PlainTextResponse(toml, media_type="application/toml")


@router.get("/generate/visitor-toml")
def gen_visitor_toml(
    config_id: str | None = Query(None),
    user_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if config_id:
        config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    else:
        config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    user = current_user
    if user_id and current_user.is_admin:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    tunnel_query = db.query(FrpTunnel).filter(
        FrpTunnel.frp_config_id == config.id,
        FrpTunnel.tunnel_type == "stcp",
        FrpTunnel.enabled.is_(True),
    )

    if user.is_admin:
        tunnels = tunnel_query.all()
    else:
        server_ids = [s.id for s in user.servers]
        if not server_ids:
            tunnels = []
        else:
            tunnels = tunnel_query.filter(FrpTunnel.server_id.in_(server_ids)).all()

    toml = generate_visitor_toml(config, tunnels, user.username)
    return PlainTextResponse(toml, media_type="application/toml")


@router.get("/generate/visitor-bundle")
def gen_visitor_bundle(
    config_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Returns TOML + PKI bundle as JSON for the desktop app."""
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

    if current_user.is_admin:
        tunnels = tunnel_query.all()
    else:
        server_ids = [s.id for s in current_user.servers]
        if not server_ids:
            tunnels = []
        else:
            tunnels = tunnel_query.filter(FrpTunnel.server_id.in_(server_ids)).all()
    toml = generate_visitor_toml(config, tunnels, current_user.username, pki_base_path="pki")

    pki = {}
    pki_status = pki_manager.get_pki_status()
    if pki_status["caExists"]:
        username = current_user.username
        client_crt = pki_manager.PKI_DIR / f"{username}.crt"
        if not client_crt.exists():
            pki_manager.generate_client_cert(username)

        ca_crt = pki_manager.PKI_DIR / "ca.crt"
        client_key = pki_manager.PKI_DIR / f"{username}.key"

        if ca_crt.exists():
            pki["ca.crt"] = ca_crt.read_text()
        if client_crt.exists():
            pki[f"{username}.crt"] = client_crt.read_text()
        if client_key.exists():
            pki[f"{username}.key"] = client_key.read_text()

    return {"toml": toml, "pki": pki}


@router.get("/generate/bulk-zip")
def gen_bulk_zip(
    config_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Generates a ZIP with frps.toml, visitor.toml and one frpc.toml per server."""
    if config_id:
        config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    else:
        config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("frps.toml", generate_frps_toml(config))

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
            allow_users = get_allow_users(db, server_id)
            frpc = generate_frpc_toml(config, tunnels, server.name, allow_users)
            zf.writestr(f"clients/{server.name}/frpc.toml", frpc)

        stcp_tunnels = [t for t in all_tunnels if t.tunnel_type == "stcp"]
        users_with_servers = db.query(User).filter(User.servers.any()).all()
        if users_with_servers:
            for user in users_with_servers:
                u_server_ids = {s.id for s in user.servers}
                u_tunnels = [t for t in stcp_tunnels if t.server_id in u_server_ids]
                if u_tunnels:
                    zf.writestr(f"visitors/{user.username}.toml", generate_visitor_toml(config, u_tunnels, user.username))
        else:
            zf.writestr("visitor.toml", generate_visitor_toml(config, stcp_tunnels))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=frp-configs.zip"},
    )
