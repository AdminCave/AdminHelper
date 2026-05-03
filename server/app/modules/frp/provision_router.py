"""FRP-Sync-Endpoints fuer den frpc-Agent.

Server-Provisioning (Token-Lifecycle, Activate) ist seit v0.23.0 in
app.modules.provisioning ausgelagert. Hier bleiben nur die laufenden
Sync-Operationen, die der Agent regelmaessig braucht.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import ApiKeyOrUser
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp._helpers import get_allow_users
from app.modules.frp.config_generator import generate_frpc_toml
from app.modules.frp import provisioner
from app.modules.servers.models import Server

router = APIRouter(prefix="/api/frp", tags=["frp"])

read_dep = ApiKeyOrUser(require_write=False)


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

    allow_users = get_allow_users(db, server_id)
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

    allow_users = get_allow_users(db, server_id)
    config_hash = provisioner.get_config_hash(config, tunnels, server.name, allow_users=allow_users)
    return {"hash": config_hash}
