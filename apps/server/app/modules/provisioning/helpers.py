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
  if FRP is configured (the frpc.toml the sync serves). Otherwise None.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import MONITOR_API_KEY, MONITOR_SERVICE_URL
from app.modules.frp._helpers import frpc_sync_inputs
from app.modules.frp.config_generator import generate_frpc_toml

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
    config exists, None is returned.

    The frpc.toml is the text the sync serves, from the inputs to
    generate_frpc_toml that frp._helpers.frpc_sync_inputs gives the sync endpoints
    as well, so bundle, config-hash and download are equal and the agent's next
    sync has nothing to do. Without an active tunnel it carries no tunnel and no
    frps token. It is not None then: an agent older than R-0398 writes its sync
    config, with the new API key, only along with a bundle."""
    inputs = frpc_sync_inputs(db, server_id)
    if inputs is None:
        return None
    config, tunnels, allow_users = inputs

    # Look up the server again in the helper so callers do not have to pass
    # a server instance
    from app.modules.servers.models import Server

    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        return None

    frpc_toml = generate_frpc_toml(config, tunnels, server.name, allow_users)

    # A7: no server-minted frp client cert anymore. The agent presents the
    # tunnel-scoped cert it enrolled at the ca-issuer (A4); the generated
    # frpc.toml points at that identity, so the bundle carries only the config.
    return {
        "config": base64.b64encode(frpc_toml.encode()).decode(),
        "pkiBundle": "",
    }
