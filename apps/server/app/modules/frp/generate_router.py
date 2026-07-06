# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.core.auth import get_current_admin, get_current_user
from app.core.database import get_db
from app.modules.frp._helpers import get_allow_users, get_frp_config
from app.modules.frp.config_generator import (
    generate_frpc_toml,
    generate_frps_toml,
    generate_visitor_toml,
)
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.servers.models import Server
from app.modules.users.models import User

router = APIRouter(prefix="/api/frp", tags=["frp"])


def _resolve_config(db: Session, config_id: str | None) -> FrpServerConfig:
    """Resolve the FRP config (by id, else the deterministic singleton) or 404.
    Wraps get_frp_config so every generate endpoint resolves it the same way (2.44)."""
    config = get_frp_config(db, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")
    return config


def _visible_stcp_tunnels(db: Session, config: FrpServerConfig, user: User) -> list[FrpTunnel]:
    """The enabled STCP tunnels of `config` visible to `user`: all for an admin,
    else only those on the user's own servers. Centralised because it is a security
    invariant — a non-admin must never see foreign tunnels, and duplicating it
    risks breaking that at one site (2.44)."""
    # Eager-load target_server: generate_visitor_toml reads tunnel.target_server.name per tunnel,
    # which would otherwise fire one SELECT per tunnel (the backref is lazy) (5.29).
    q = (
        db.query(FrpTunnel)
        .options(joinedload(FrpTunnel.target_server))
        .filter(
            FrpTunnel.frp_config_id == config.id,
            FrpTunnel.tunnel_type == "stcp",
            FrpTunnel.enabled.is_(True),
        )
    )
    if user.is_admin:
        return q.all()
    server_ids = [s.id for s in user.servers]
    if not server_ids:
        return []
    return q.filter(FrpTunnel.server_id.in_(server_ids)).all()


@router.get("/generate/frps-toml")
def gen_frps_toml(
    config_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    config = _resolve_config(db, config_id)
    toml = generate_frps_toml(config)
    return PlainTextResponse(toml, media_type="application/toml")


@router.get("/generate/frpc-toml/{server_id}")
def gen_frpc_toml(server_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    tunnels = (
        db.query(FrpTunnel)
        .filter(
            FrpTunnel.server_id == server_id,
            FrpTunnel.enabled.is_(True),
        )
        .all()
    )
    if not tunnels:
        raise HTTPException(status_code=404, detail="Keine aktiven Tunnel fuer diesen Server")

    config = (
        db.query(FrpServerConfig).filter(FrpServerConfig.id == tunnels[0].frp_config_id).first()
    )
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
    config = _resolve_config(db, config_id)

    user = current_user
    if user_id and current_user.is_admin:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    tunnels = _visible_stcp_tunnels(db, config, user)
    # The visitor TOML embeds the shared frps auth token; without visible STCP
    # tunnels the user has no legitimate reason for it, so refuse rather than hand
    # the global secret to any authenticated (non-admin, server-less) user (3.33).
    if not tunnels:
        raise HTTPException(status_code=404, detail="Keine sichtbaren STCP-Tunnel")

    toml = generate_visitor_toml(config, tunnels, user.username)
    return PlainTextResponse(toml, media_type="application/toml")


@router.get("/generate/visitor-bundle")
def gen_visitor_bundle(
    config_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Returns the visitor TOML as JSON for the desktop app.

    The PKI material is no longer server-minted (F2/F3: the server holds no
    signing capability, D6). The desktop supplies its own enrolled access identity
    for the visitor's mTLS, so the bundle carries only the TOML; ``pki`` stays
    empty for backward compatibility with the desktop's response shape."""
    config = _resolve_config(db, config_id)

    tunnels = _visible_stcp_tunnels(db, config, current_user)
    # See gen_visitor_toml: don't hand the shared frps auth token to a user with no
    # visible STCP tunnels (3.33).
    if not tunnels:
        raise HTTPException(status_code=404, detail="Keine sichtbaren STCP-Tunnel")
    toml = generate_visitor_toml(config, tunnels, current_user.username)

    return {"toml": toml, "pki": {}}


@router.get("/generate/bulk-zip")
def gen_bulk_zip(
    config_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Generates a ZIP with frps.toml, visitor.toml and one frpc.toml per server."""
    config = _resolve_config(db, config_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("frps.toml", generate_frps_toml(config))

        all_tunnels = (
            db.query(FrpTunnel)
            .options(
                joinedload(FrpTunnel.target_server)
            )  # 5.29: no per-tunnel target_server SELECT
            .filter(
                FrpTunnel.frp_config_id == config.id,
                FrpTunnel.enabled.is_(True),
            )
            .all()
        )

        by_server = {}
        for t in all_tunnels:
            by_server.setdefault(t.server_id, []).append(t)

        servers = db.query(Server).filter(Server.id.in_(by_server.keys())).all()
        servers_by_id = {s.id: s for s in servers}

        for server_id, tunnels in by_server.items():
            server = servers_by_id.get(server_id)
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
                    zf.writestr(
                        f"visitors/{user.username}.toml",
                        generate_visitor_toml(config, u_tunnels, user.username),
                    )
        else:
            zf.writestr("visitor.toml", generate_visitor_toml(config, stcp_tunnels))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=frp-configs.zip"},
    )
