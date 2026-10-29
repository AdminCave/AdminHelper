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
  "frp": {                          // if FRP is configured (no tunnel, no frps
                                    // token without an active tunnel)
    "config": "<base64 frpc.toml>",
    "pkiBundle": ""                 // always empty since A7: the agent enrolls
                                    // its tunnel cert itself
  } | null,
  "enrollment": {                   // one-time grant for the mTLS client cert
    "token": "...",                 // single-use, redeemed at the ca-issuer /enroll
    "subjectId": "<server_id>",     // the cert CN (issuer-dictated, not the CSR)
    "scope": "tunnel",              // agent scope
    "enrollPort": 8444              // gateway enroll plane; agent adds its own host
  }
}
"""

from __future__ import annotations

import datetime
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.auth import generate_api_key, get_current_admin, hash_api_key
from app.core.config import ENROLL_PORT
from app.core.database import get_db
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT, require_scope
from app.core.request_context import actor_from_request
from app.core.time import iso_utc, utcnow_naive
from app.modules.api_keys.models import ApiKey
from app.modules.audit import service as audit
from app.modules.enrollment.service import mint_enrollment_token
from app.modules.provisioning.helpers import build_frp_bundle, fetch_or_skip_monitor_key
from app.modules.provisioning.models import ProvisionToken
from app.modules.provisioning.schemas import (
    ActivateOut,
    ProvisionTokenCreatedOut,
    ProvisionTokenOut,
)
from app.modules.servers.models import Server

router = APIRouter(prefix="/api/servers", tags=["provisioning"])


@router.post("/{server_id}/provision/token", response_model=ProvisionTokenCreatedOut)
def create_provision_token(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
    _scope=Depends(require_scope(SCOPE_ACCESS)),
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
        expires_at=utcnow_naive() + datetime.timedelta(hours=24),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    audit.record(
        db,
        "provision.token.minted",
        object_type="server",
        object_id=server_id,
        object_label=server.name,
        detail="ttl=24h",
        actor=actor_from_request(request),
    )

    return {
        "token": raw_token,
        "expiresAt": iso_utc(token.expires_at),
        "serverId": server_id,
        "serverName": server.name,
    }


@router.get("/{server_id}/provision/tokens", response_model=list[ProvisionTokenOut])
def list_provision_tokens(
    server_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
    _scope=Depends(require_scope(SCOPE_ACCESS)),
):
    """Lists all provision tokens for a server."""
    tokens = (
        db.query(ProvisionToken)
        .filter(ProvisionToken.server_id == server_id)
        .order_by(ProvisionToken.created_at.desc())
        .all()
    )
    return [t.to_dict() for t in tokens]


@router.post("/{server_id}/provision/activate", response_model=ActivateOut)
def activate_provision(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Redeems a provision token. Returns the server API key (always),
    monitor agent key (if service is available), FRP bundle (if FRP is configured).

    Deliberately NO mTLS scope guard: this is a bootstrap door — the agent has no
    cert yet (it gets its identity here / via enroll). It stays token-gated +
    certless even under enforcement (A8), like the ca-issuer enroll plane."""
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

    # FOR NO KEY UPDATE on the server row, held until the activation commits, after the
    # API key, the monitor key and the enrollment token all exist: a second activation of
    # the same server (with another token) waits, then replaces all of them, so what the
    # agent gets comes from one activation (R-0291, R-0311). The weaker lock still lets
    # foreign keys to the server through.
    server = db.query(Server).filter(Server.id == server_id).with_for_update(key_share=True).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    # Consume the token atomically (TOCTOU protection): a conditional UPDATE
    # serializes parallel redemptions via the row lock -> exactly ONE request wins;
    # all others get rowcount 0 and are rejected BEFORE a key is created.
    consumed = (
        db.query(ProvisionToken)
        .filter(ProvisionToken.id == token.id, ProvisionToken.used_at.is_(None))
        .update(
            {ProvisionToken.used_at: utcnow_naive()},
            synchronize_session=False,
        )
    )
    if consumed == 0:
        raise HTTPException(status_code=409, detail="Token wurde bereits eingeloest")

    # 1. Server read API key (always). It replaces the key of an earlier provisioning:
    # the agent installed now is the one that holds the server's key (R-0279). Keys bound
    # to a server only come from here; manually created keys carry no server_id (except
    # ones named agent-<server> before c3a7e1f50b2d, which that migration bound).
    replaced = db.query(ApiKey).filter(ApiKey.server_id == server_id).all()
    for old_key in replaced:
        db.delete(old_key)
    raw_api_key = generate_api_key()
    api_key = ApiKey(
        name=f"agent-{server.name}",
        hashed_key=hash_api_key(raw_api_key),
        permission="read",
        server_id=server_id,  # bound to exactly this server (IDOR protection)
    )
    db.add(api_key)
    replaced_keys = [(old_key.id, old_key.name) for old_key in replaced]

    # 2. Monitor agent key (resilient: None on error). The monitoring service keeps one
    # key per server and replaces it here; it does not call back into this database.
    monitor_key = fetch_or_skip_monitor_key(server_id)

    # 3. FRP bundle (only if FRP is configured; the frpc.toml the sync serves)
    frp_bundle = build_frp_bundle(server_id, db)

    # 4. One-time enrollment token (tunnel scope = agent, ADR 0001 §3.1 / A3).
    # The agent enrolls its mTLS client cert at the ca-issuer right after this.
    # Minted via the shared service so the hashing (the SHA-256 the ca-issuer
    # consumes by) and TTL stay in lockstep with the HTTP enrollment path (2.51);
    # identity (CN) is the stable server_id, not the client's CSR.
    raw_enroll_token = mint_enrollment_token(db, server_id, SCOPE_AGENT)
    # The end of the activation: the spent provision token, the keys and the enrollment
    # token at once (mint_enrollment_token commits as well), and the server row is free
    # again. The audit entries commit on their own, so they come after it.
    db.commit()
    for key_id, key_name in replaced_keys:
        audit.record(
            db,
            "apikey.deleted",
            object_type="api_key",
            object_id=key_id,
            object_label=key_name,
            detail="replaced by a new provisioning of the server",
            actor=actor_from_request(request),
        )
    audit.record(
        db,
        "enrollment.token.minted",
        object_type="server",
        object_id=server_id,
        detail="scope=agent (provisioning)",
        actor=actor_from_request(request),
    )

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
        # The agent derives the enroll host from its own server URL + this port
        # (the gateway's certless enroll plane), then POSTs token + CSR there.
        "enrollment": {
            "token": raw_enroll_token,
            "subjectId": server_id,
            "scope": SCOPE_AGENT,
            "enrollPort": ENROLL_PORT,
        },
    }
