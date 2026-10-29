# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FRP sync endpoints for the frpc agent.

Server provisioning (token lifecycle, activate) has been moved to
app.modules.provisioning since v0.23.0. Only the ongoing sync operations
that the agent needs regularly remain here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.auth import ApiKeyOrUser
from app.core.database import get_db
from app.core.identity import require_cert_server
from app.modules.frp import provisioner
from app.modules.frp._helpers import frpc_sync_inputs
from app.modules.frp.config_generator import generate_frpc_toml
from app.modules.frp.schemas import ConfigHashOut
from app.modules.servers.models import Server

router = APIRouter(prefix="/api/frp", tags=["frp"])

# require_admin=True: JWT users must be admins — the frpc.toml contains global
# FRP secrets (auth.token + STCP secret_keys). API keys are additionally checked
# by server_id scope (see _require_server_scope).
read_dep = ApiKeyOrUser(require_write=False, require_admin=True)


def _require_server_scope(auth, server_id: str) -> None:
    """IDOR protection: an API key (agent) may read ONLY its own server.
    JWT users (interactive admin management) are not bound to a server. The check
    runs BEFORE the 404 existence check to prevent server-ID enumeration."""
    _user, api_key = auth
    if api_key is not None and api_key.server_id != server_id:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diesen Server")


def _load_sync_inputs(db: Session, server_id: str, auth):
    """The inputs both provision-sync endpoints share (config download + config
    hash): scope check, server lookup, and config, tunnels and allow-users from
    frp._helpers.frpc_sync_inputs, which the provisioning bundle uses as well.
    None without an FRP config: the two endpoints answer that differently."""
    _require_server_scope(auth, server_id)
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    inputs = frpc_sync_inputs(db, server_id)
    if inputs is None:
        return None
    config, tunnels, allow_users = inputs
    return config, tunnels, server.name, allow_users


@router.get("/provision/{server_id}/config", dependencies=[Depends(require_cert_server)])
def get_provision_config(
    server_id: str,
    db: Session = Depends(get_db),
    auth=Depends(read_dep),
):
    """Returns the current frpc.toml for the sync agent."""
    inputs = _load_sync_inputs(db, server_id, auth)
    if inputs is None:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")
    config, tunnels, server_name, allow_users = inputs
    toml_content = generate_frpc_toml(config, tunnels, server_name, allow_users)
    return PlainTextResponse(toml_content, media_type="application/toml")


@router.get(
    "/provision/{server_id}/config-hash",
    response_model=ConfigHashOut,
    dependencies=[Depends(require_cert_server)],
)
def get_provision_config_hash(
    server_id: str,
    db: Session = Depends(get_db),
    auth=Depends(read_dep),
):
    """Returns the SHA256 hash of the current frpc.toml."""
    inputs = _load_sync_inputs(db, server_id, auth)
    if inputs is None:
        # Without an FRP config the hash is null: nothing to sync, which is not an
        # error. The agent reads a 404 as permanent and would fail every timer run
        # on a host without FRP (R-0398). With a config but no active tunnel the
        # hash is the one of the generator's text without a tunnel and without the
        # frps credentials, so every agent that applies it keeps no tunnel up.
        return {"hash": None}
    config, tunnels, server_name, allow_users = inputs
    config_hash = provisioner.get_config_hash(config, tunnels, server_name, allow_users=allow_users)
    return {"hash": config_hash}
