# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import uuid
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import VISITOR_PORT_END, VISITOR_PORT_START
from app.modules.connections.models import Connection
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.schemas import check_auto_path
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


def connection_kind(protocol: str) -> str:
    """The kind of the connection a tunnel of `protocol` leads to."""
    return "ssh" if protocol == "ssh" else "rdp" if protocol == "rdp" else "web"


def _first_domain(tunnel: FrpTunnel) -> str:
    return (tunnel.custom_domains or "").split(",")[0].strip()


def tunnel_url(tunnel: FrpTunnel, scheme: str | None, path: str | None) -> str | None:
    """The URL of a web connection through `tunnel`. An STCP one names the visitor port; the
    desktop replaces only host and port with those of its visitor and keeps scheme and path
    (R-1540)."""
    if tunnel.tunnel_type == "stcp" and tunnel.visitor_port:
        return f"{scheme or 'http'}://127.0.0.1:{tunnel.visitor_port}{path or ''}"
    if tunnel.tunnel_type == "https" and _first_domain(tunnel):
        return f"https://{_first_domain(tunnel)}{path or ''}"
    return None


def create_auto_connection(
    tunnel: FrpTunnel,
    username: str | None = None,
    scheme: str | None = None,
    path: str | None = None,
) -> Connection | None:
    """Create an auto-connection for a tunnel (STCP or HTTPS). It stores no name: its display
    name derives from the server's (R-1210). An STCP web one has no user (R-1540)."""
    if tunnel.tunnel_type == "stcp" and tunnel.visitor_port:
        conn_kind = connection_kind(tunnel.protocol)
        web = conn_kind == "web"
        return Connection(
            id=str(uuid.uuid4()),
            name="",
            kind=conn_kind,
            host="127.0.0.1",
            port=tunnel.visitor_port,
            url=tunnel_url(tunnel, scheme, path) if web else "",
            server_id=tunnel.server_id,
            tags=tunnel.tags,
            username="" if web else username or "",
        )
    if tunnel.tunnel_type == "https" and _first_domain(tunnel):
        return Connection(
            id=str(uuid.uuid4()),
            name="",
            kind="web",
            url=tunnel_url(tunnel, "https", path),
            server_id=tunnel.server_id,
            tags=tunnel.tags,
            username=username or "",
        )
    return None


def follow_tunnel(
    connection: Connection, tunnel: FrpTunnel, scheme: str | None, path: str | None
) -> None:
    """Point the connection linked to `tunnel` at it again after its protocol or type changed
    (R-1540), a hand-linked one too. A scheme or path not given comes from the connection's own
    web URL, else http and none. A path the request would refuse is not taken: it could move the
    host of the new URL."""
    old = urlsplit(connection.url or "") if connection.kind == "web" else None
    if old is None or old.scheme not in ("http", "https"):
        old = None
    if old is not None and scheme is None:
        scheme = old.scheme
    if old is not None and path is None and old.path:
        try:
            path = check_auto_path(old.path + (f"?{old.query}" if old.query else ""))
        except ValueError:
            path = None
    connection.kind = connection_kind(tunnel.protocol)
    if tunnel.tunnel_type == "stcp":
        connection.host = "127.0.0.1"
        connection.port = tunnel.visitor_port
    web_url = tunnel_url(tunnel, scheme, path) if connection.kind == "web" else None
    connection.url = web_url or ""


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

    Admins are automatically authorized for all servers. Sorted: the list ends up
    in allowUsers and the agent's config hash, and a set's order follows the
    per-process hash seed, so the hash would change on every restart.
    """
    # Fail CLOSED: if nobody resolves (no assigned users AND no admins — only
    # reachable if all admins were demoted, which update_user now also blocks),
    # return an empty allow-list (the config_generator then falls back to the
    # admin visitor), NOT ["*"] which would let ANY visitor reach the tunnel.
    return allow_users_by_server(db, [server_id])[server_id]


def allow_users_by_server(db: Session, server_ids) -> dict[str, list[str]]:
    """get_allow_users for each of server_ids in two queries, however many there are: the
    policy and the bulk ZIP build every host's list (R-1699)."""
    ids = list(server_ids)
    admins = {name for (name,) in db.query(User.username).filter(User.is_admin.is_(True))}
    assigned: dict[str, set[str]] = {server_id: set() for server_id in ids}
    if ids:
        rows = (
            db.query(user_server_assoc.c.server_id, User.username)
            .select_from(user_server_assoc)
            .join(User, User.id == user_server_assoc.c.user_id)
            .filter(user_server_assoc.c.server_id.in_(ids))
        )
        for server_id, name in rows:
            assigned[server_id].add(name)
    return {server_id: sorted(admins | names) for server_id, names in assigned.items()}


def frpc_sync_inputs(
    db: Session, server_id: str
) -> tuple[FrpServerConfig, list[FrpTunnel], list[str]] | None:
    """The generate_frpc_toml inputs the agent's frpc.toml is built from: the FRP
    config, the tunnels scoped to this server AND this config, and the allow-users.
    Shared by the provision-sync endpoints (config download + config hash) and the
    provisioning bundle, so the three can't drift: a hash computed over a different
    tunnel set than the download would trigger endless agent resyncs (2.45), and a
    bundle unlike the sync text would leave the agent's first sync with work to do.
    None without an FRP config; the server lookup stays with the callers."""
    config = get_frp_config(db)
    if not config:
        return None

    tunnels = (
        db.query(FrpTunnel)
        .filter(
            FrpTunnel.server_id == server_id,
            FrpTunnel.frp_config_id == config.id,
        )
        .all()
    )
    return config, tunnels, get_allow_users(db, server_id)
