# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Server provisioning endpoints (FRP-independent).

POST /api/servers/{server_id}/provision/token       — create token (admin)
GET  /api/servers/{server_id}/provision/tokens      — list active tokens (admin)
POST /api/servers/{server_id}/provision/activate    — redeem token (X-Provision-Token)

Activate response schema:
{
  "serverName": "k01-lnx1",
  "apiKey": "...",                  // always: server read API key
  "monitorApiKey": "..." | null,    // if monitor service is reachable
  "monitorUrl": "/api/monitoring" | null,  // server-relative path; the agent
                                    // joins it to its own trusted server URL
  "frp": {                          // if the server has FRP tunnels configured
    "config": "<base64 frpc.toml>",
    "pkiBundle": "<base64 tar.gz>"
  } | null
}
"""

from __future__ import annotations

import datetime
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin, hash_api_key, generate_api_key
from app.modules.api_keys.models import ApiKey
from app.modules.provisioning.helpers import build_frp_bundle, fetch_or_skip_monitor_key
from app.modules.provisioning.models import ProvisionToken
from app.modules.servers.models import Server

router = APIRouter(prefix="/api/servers", tags=["provisioning"])


@router.post("/{server_id}/provision/token")
def create_provision_token(
    server_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Creates a one-time server provision token (valid for 24h)."""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    raw_token = f"adminhelper_prov_{secrets.token_urlsafe(32)}"
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


@router.get("/{server_id}/provision/tokens")
def list_provision_tokens(
    server_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Lists all provision tokens for a server."""
    tokens = db.query(ProvisionToken).filter(
        ProvisionToken.server_id == server_id
    ).order_by(ProvisionToken.created_at.desc()).all()
    return [t.to_dict() for t in tokens]


@router.post("/{server_id}/provision/activate")
def activate_provision(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Redeems a provision token. Returns the server API key (always),
    monitor agent key (if service is available), FRP bundle (if tunnels exist)."""
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

    # Consume the token atomically (TOCTOU protection): a conditional UPDATE
    # serializes parallel redemptions via the row lock -> exactly ONE request wins;
    # all others get rowcount 0 and are rejected BEFORE a key is created.
    consumed = (
        db.query(ProvisionToken)
        .filter(ProvisionToken.id == token.id, ProvisionToken.used_at.is_(None))
        .update(
            {ProvisionToken.used_at: datetime.datetime.now(datetime.timezone.utc)},
            synchronize_session=False,
        )
    )
    if consumed == 0:
        raise HTTPException(status_code=409, detail="Token wurde bereits eingeloest")

    # 1. Server read API key (always)
    raw_api_key = generate_api_key()
    api_key = ApiKey(
        name=f"agent-{server.name}",
        hashed_key=hash_api_key(raw_api_key),
        permission="read",
        server_id=server_id,  # bound to exactly this server (IDOR protection)
    )
    db.add(api_key)
    db.commit()

    # 2. Monitor agent key (resilient: None on error)
    monitor_key = fetch_or_skip_monitor_key(server_id)

    # 3. FRP bundle (only if FRP is configured + tunnels exist)
    frp_bundle = build_frp_bundle(server_id, db)

    return {
        "serverName": server.name,
        "apiKey": raw_api_key,
        "monitorApiKey": monitor_key,
        # Server-relative path under the public API. The agent prepends the same
        # server URL it provisioned against (already TLS-trusted), so the metrics
        # push reaches monitoring via the server proxy on 443 without the server
        # needing to know its own public address. None when monitoring is down.
        "monitorUrl": "/api/monitoring" if monitor_key else None,
        "frp": frp_bundle,
    }
