# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import VISITOR_PORT_END, VISITOR_PORT_START
from app.modules.connections.models import Connection
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.users.models import User, user_server_assoc


def get_frp_config(db: Session, config_id: str | None = None) -> FrpServerConfig | None:
    """Resolve the FRP server config.

    FrpServerConfig is a multi-row table treated as a singleton by most callers.
    Resolve it deterministically — oldest first, id as tiebreaker — instead of a
    bare `.first()`: on Postgres an unordered `.first()` may return a different
    row each call, so with two configs the agent sync / startup frps.toml could
    otherwise pick a random one (serverAddr/auth_token mismatch, dead tunnel).
    """
    q = db.query(FrpServerConfig)
    if config_id:
        return q.filter(FrpServerConfig.id == config_id).first()
    return q.order_by(FrpServerConfig.created_at, FrpServerConfig.id).first()


def create_auto_connection(
    name: str,
    tunnel_type: str,
    protocol: str | None,
    custom_domains: str | None,
    visitor_port: int | None,
    server_id: str,
    db: Session,
    tags: str | None = None,
    username: str | None = None,
) -> Connection | None:
    """Create an auto-connection for a tunnel (STCP or HTTPS)."""
    if tunnel_type == "stcp" and visitor_port:
        conn_kind = "ssh" if protocol == "ssh" else "rdp" if protocol == "rdp" else "web"
        return Connection(
            id=str(uuid.uuid4()),
            name=f"{name} (via FRP)",
            kind=conn_kind,
            host="127.0.0.1",
            port=visitor_port,
            server_id=server_id,
            tags=tags,
            username=username or "",
        )
    if tunnel_type == "https" and custom_domains:
        domain = custom_domains.split(",")[0].strip()
        if domain:
            return Connection(
                id=str(uuid.uuid4()),
                name=f"{name} (via FRP)",
                kind="web",
                url=f"https://{domain}",
                server_id=server_id,
                tags=tags,
                username=username or "",
            )
    return None


def next_visitor_port(db: Session, exclude_tunnel_id: str | None = None) -> int:
    """Determine the next free visitor port from the configured range."""
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


def get_allow_users(db: Session, server_id: str) -> list[str]:
    """Determine all usernames that have access to this server.

    Admins are automatically authorized for all servers.
    """
    assigned = (
        db.query(User)
        .join(user_server_assoc, User.id == user_server_assoc.c.user_id)
        .filter(user_server_assoc.c.server_id == server_id)
        .all()
    )
    admins = db.query(User).filter(User.is_admin.is_(True)).all()
    names = list({u.username for u in [*assigned, *admins]})
    # Fail CLOSED: if nobody resolves (no assigned users AND no admins — only
    # reachable if all admins were demoted, which update_user now also blocks),
    # return an empty allow-list (the config_generator then falls back to the
    # admin visitor), NOT ["*"] which would let ANY visitor reach the tunnel.
    return names
