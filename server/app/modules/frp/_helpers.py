import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import VISITOR_PORT_START, VISITOR_PORT_END
from app.modules.frp.models import FrpTunnel
from app.modules.connections.models import Connection
from app.modules.users.models import User, user_server_assoc


def create_auto_connection(
    name: str,
    tunnel_type: str,
    protocol: str | None,
    custom_domains: str | None,
    visitor_port: int | None,
    server_id: str,
    db: Session,
) -> Connection | None:
    """Auto-Connection fuer einen Tunnel erstellen (STCP oder HTTPS)."""
    if tunnel_type == "stcp" and visitor_port:
        conn_kind = "ssh" if protocol == "ssh" else "rdp" if protocol == "rdp" else "web"
        return Connection(
            id=str(uuid.uuid4()),
            name=f"{name} (via FRP)",
            kind=conn_kind,
            host="127.0.0.1",
            port=visitor_port,
            server_id=server_id,
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
            )
    return None


def next_visitor_port(db: Session, exclude_tunnel_id: str | None = None) -> int:
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


def get_allow_users(db: Session, server_id: str) -> list[str]:
    """Ermittelt alle Usernamen, die Zugriff auf diesen Server haben.

    Admins sind automatisch fuer alle Server berechtigt.
    """
    assigned = (
        db.query(User)
        .join(user_server_assoc, User.id == user_server_assoc.c.user_id)
        .filter(user_server_assoc.c.server_id == server_id)
        .all()
    )
    admins = db.query(User).filter(User.is_admin.is_(True)).all()
    names = list({u.username for u in [*assigned, *admins]})
    return names if names else ["*"]
