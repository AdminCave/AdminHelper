# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers for the server provisioning flow.

Two tasks that must work independently of each other:
- fetch_or_skip_monitor_key: calls the monitoring service internally,
  generates a new agent key there and returns it. On error (service down,
  wrong internal key, network gone) it returns None and logs a WARNING —
  a provisioning request should never fail because of a downed monitor
  service.
- build_frp_bundle: builds frpc.toml + PKI bundle (base64) for a server
  if FRP is configured AND the server has tunnels. Otherwise None.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import MONITOR_SERVICE_URL, MONITOR_API_KEY
from app.modules.frp import pki as pki_manager
from app.modules.frp import provisioner
from app.modules.frp._helpers import get_allow_users
from app.modules.frp.config_generator import generate_frpc_toml
from app.modules.frp.models import FrpServerConfig, FrpTunnel

logger = logging.getLogger("adminhelper.provisioning")


def fetch_or_skip_monitor_key(server_id: str, timeout: float = 5.0) -> Optional[str]:
    """Requests a new monitor agent key from the monitoring service.

    Note: creates a NEW key — if one already existed, it is invalidated
    (the monitoring-service endpoint deletes old keys on
    POST /agent-keys/{id}).

    On error (service unreachable, wrong internal key, etc.) it returns
    None and logs a WARNING — provisioning should not fail because of a
    downed monitor service.
    """
    if not MONITOR_API_KEY:
        logger.warning(
            "Provisioning: MONITOR_API_KEY ist leer, kann Monitor-Agent-Key "
            "nicht generieren. Setze MONITOR_API_KEY oder fuehre "
            "scripts/init-secrets.sh aus."
        )
        return None

    url = f"{MONITOR_SERVICE_URL.rstrip('/')}/agent-keys/{server_id}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers={"X-Internal-Key": MONITOR_API_KEY})
        if resp.status_code >= 300:
            logger.warning(
                "Provisioning: Monitor-Service antwortete mit %d auf %s — "
                "kein Monitor-Key in Antwort enthalten",
                resp.status_code,
                url,
            )
            return None
        data = resp.json()
        # The monitoring-service response contains 'apiKey' (raw) as a one-time value
        return data.get("apiKey")
    except httpx.HTTPError as exc:
        logger.warning(
            "Provisioning: Monitor-Service unter %s nicht erreichbar (%s) — "
            "kein Monitor-Key in Antwort enthalten",
            url,
            exc,
        )
        return None


def build_frp_bundle(server_id: str, db: Session) -> Optional[dict[str, Any]]:
    """Builds frpc.toml + PKI bundle for a server. Optional — if no FRP
    config exists OR the server has no tunnels, None is returned."""
    config = db.query(FrpServerConfig).first()
    if not config:
        return None

    tunnels = db.query(FrpTunnel).filter(
        FrpTunnel.server_id == server_id,
        FrpTunnel.frp_config_id == config.id,
    ).all()
    if not tunnels:
        return None

    # Look up the server again in the helper so callers do not have to pass
    # a server instance
    from app.modules.servers.models import Server
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        return None

    # If auto-PKI is active and the client cert is still missing: create it now
    pki_status = pki_manager.get_pki_status()
    if pki_status["caExists"]:
        client_crt = pki_manager.PKI_DIR / f"{server.name}.crt"
        if not client_crt.exists():
            pki_manager.generate_client_cert(server.name)

    allow_users = get_allow_users(db, server_id)
    frpc_toml = generate_frpc_toml(config, tunnels, server.name, allow_users)
    pki_bundle = provisioner.build_pki_bundle_b64(server.name)

    return {
        "config": base64.b64encode(frpc_toml.encode()).decode(),
        "pkiBundle": pki_bundle or "",
    }
