"""Helpers fuer den Server-Provisioning-Flow.

Zwei Aufgaben, die unabhaengig voneinander funktionieren muessen:
- fetch_or_skip_monitor_key: ruft den Monitoring-Service intern auf,
  generiert dort einen neuen Agent-Key, gibt ihn zurueck. Bei Fehler
  (Service down, Internal-Key falsch, Netzwerk weg) wird None geliefert
  und ein WARNING geloggt — Provisioning-Request soll nie an einem
  ausgefallenen Monitor-Service scheitern.
- build_frp_bundle: erzeugt frpc.toml + PKI-Bundle (base64) fuer einen
  Server, wenn FRP konfiguriert ist UND der Server Tunnel hat. Sonst None.
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
    """Fragt einen neuen Monitor-Agent-Key beim Monitoring-Service an.

    Achtung: erzeugt einen NEUEN Key — falls bereits einer existierte,
    wird er invalidiert (Monitoring-Service-Endpoint loescht alte Keys
    bei POST /agent-keys/{id}).

    Bei Fehler (Service nicht erreichbar, falscher Internal-Key, etc.)
    wird None zurueckgegeben und WARNING geloggt — Provisioning soll
    nicht an einem ausgefallenen Monitor-Service scheitern.
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
        # Monitoring-Service-Antwort enthaelt 'apiKey' (raw) als one-time-Wert
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
    """Baut frpc.toml + PKI-Bundle fuer einen Server. Optional — wenn
    keine FRP-Config existiert ODER der Server keine Tunnel hat,
    wird None geliefert."""
    config = db.query(FrpServerConfig).first()
    if not config:
        return None

    tunnels = db.query(FrpTunnel).filter(
        FrpTunnel.server_id == server_id,
        FrpTunnel.frp_config_id == config.id,
    ).all()
    if not tunnels:
        return None

    # Server-Lookup nochmal im Helper, damit die Aufrufer keine Server-
    # Instance reichen muessen
    from app.modules.servers.models import Server
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        return None

    # Falls Auto-PKI aktiv ist und das Client-Cert noch fehlt: jetzt erzeugen
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
