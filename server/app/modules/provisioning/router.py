# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Server-Provisioning-Endpoints (FRP-unabhaengig).

POST /api/servers/{server_id}/provision/token       — Token erstellen (admin)
GET  /api/servers/{server_id}/provision/tokens      — Aktive Tokens listen (admin)
POST /api/servers/{server_id}/provision/activate    — Token einloesen (X-Provision-Token)

Activate-Antwort-Schema:
{
  "serverName": "k01-lnx1",
  "apiKey": "...",                  // immer: Server-Read-API-Key
  "monitorApiKey": "..." | null,    // wenn Monitor-Service erreichbar
  "monitorUrl": "..." | null,
  "frp": {                          // wenn Server FRP-Tunnel konfiguriert hat
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
from app.core.config import MONITOR_SERVICE_URL
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
    """Erstellt einen einmaligen Server-Provision-Token (24h gueltig)."""
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
    """Listet alle Provision-Tokens fuer einen Server auf."""
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
    """Loest einen Provision-Token ein. Liefert Server-API-Key (immer),
    Monitor-Agent-Key (wenn Service da), FRP-Bundle (wenn Tunnel da)."""
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

    # Token atomar verbrauchen (TOCTOU-Schutz): bedingtes UPDATE serialisiert
    # parallele Einloesungen ueber die Row-Lock -> genau EIN Request gewinnt; alle
    # weiteren bekommen rowcount 0 und werden abgewiesen, BEVOR ein Key entsteht.
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

    # 1. Server-Read-API-Key (immer)
    raw_api_key = generate_api_key()
    api_key = ApiKey(
        name=f"agent-{server.name}",
        hashed_key=hash_api_key(raw_api_key),
        permission="read",
    )
    db.add(api_key)
    db.commit()

    # 2. Monitor-Agent-Key (resilient: bei Fehler None)
    monitor_key = fetch_or_skip_monitor_key(server_id)

    # 3. FRP-Bundle (nur wenn FRP konfiguriert + Tunnels da)
    frp_bundle = build_frp_bundle(server_id, db)

    return {
        "serverName": server.name,
        "apiKey": raw_api_key,
        "monitorApiKey": monitor_key,
        "monitorUrl": MONITOR_SERVICE_URL.rstrip("/") if monitor_key else None,
        "frp": frp_bundle,
    }
