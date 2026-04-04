"""
OPNsense Checker — Gateway-Status, Interface-Status via REST API.

Config-Parameter:
  credential_id: ID des OPNsense-Credentials (Typ: opnsense_api)
  host: OPNsense-Host (IP/Hostname)
  port: API-Port (default 443)
  verify_ssl: SSL verifizieren (default false)
  check_mode: "gateways" (default), "interfaces", "services"

OPNsense-API Credential Config:
  api_key: API-Key
  api_secret: API-Secret
"""

from __future__ import annotations

import json
import logging

import httpx

logger = logging.getLogger("monitor.checker.opnsense")


def _load_credential(credential_id: str) -> dict:
    from app.core.database import SessionLocal
    from app.models import MonitorCredential

    db = SessionLocal()
    try:
        cred = db.query(MonitorCredential).filter(MonitorCredential.id == credential_id).first()
        if not cred:
            return {}
        return json.loads(cred.config) if cred.config else {}
    finally:
        db.close()


class OpnsenseChecker:
    """Prueft OPNsense Firewall via REST API."""

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        cred_id = config.get("credential_id", "")
        if not cred_id:
            return "unknown", "Kein credential_id konfiguriert", None

        cred = _load_credential(cred_id)
        api_key = cred.get("api_key", "")
        api_secret = cred.get("api_secret", "")
        if not api_key or not api_secret:
            return "unknown", "OPNsense-API-Key unvollstaendig", None

        host = config.get("host", "")
        port = int(config.get("port", 443))
        verify = config.get("verify_ssl", False)
        check_mode = config.get("check_mode", "gateways")

        if not host:
            return "unknown", "Kein Host angegeben", None

        base_url = f"https://{host}:{port}/api"
        client = httpx.Client(
            base_url=base_url,
            auth=(api_key, api_secret),
            verify=verify,
            timeout=10,
        )

        try:
            if check_mode == "gateways":
                return self._check_gateways(client, config)
            elif check_mode == "interfaces":
                return self._check_interfaces(client, config)
            elif check_mode == "services":
                return self._check_services(client, config)
            else:
                return "unknown", f"Unbekannter check_mode: {check_mode}", None
        except httpx.HTTPStatusError as e:
            return "critical", f"API-Fehler: HTTP {e.response.status_code}", None
        except Exception as e:
            return "critical", f"Verbindungsfehler: {e}", None
        finally:
            client.close()

    def _check_gateways(self, client: httpx.Client, config: dict) -> tuple[str, str, dict | None]:
        resp = client.get("/routes/gateway/status")
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        if not items:
            return "warning", "Keine Gateways gefunden", None

        metrics = {}
        down = []
        for gw in items:
            name = gw.get("name", "?")
            status_text = gw.get("status_translated", gw.get("status", ""))

            # RTT extrahieren
            rtt_str = gw.get("delay", "")
            try:
                rtt = float(rtt_str.replace("ms", "").strip())
                metrics[f"opnsense_gw_rtt_{name}"] = rtt
            except (ValueError, AttributeError):
                pass

            loss_str = gw.get("loss", "")
            try:
                loss = float(loss_str.replace("%", "").strip())
                metrics[f"opnsense_gw_loss_{name}"] = loss
            except (ValueError, AttributeError):
                pass

            if "down" in status_text.lower() or "offline" in status_text.lower():
                down.append(name)

        if down:
            return "critical", f"Gateways down: {', '.join(down)}", metrics

        return "ok", f"Alle {len(items)} Gateways online", metrics

    def _check_interfaces(self, client: httpx.Client, config: dict) -> tuple[str, str, dict | None]:
        resp = client.get("/diagnostics/interface/getInterfaceStatistics")
        resp.raise_for_status()
        data = resp.json()

        metrics = {}
        total = 0
        up = 0

        for iface_name, stats in data.items():
            if isinstance(stats, dict):
                total += 1
                # Pruefen ob Interface "up" ist via Traffic-Statistiken
                in_bytes = stats.get("bytes received", 0)
                out_bytes = stats.get("bytes transmitted", 0)
                metrics[f"opnsense_if_in_{iface_name}"] = in_bytes
                metrics[f"opnsense_if_out_{iface_name}"] = out_bytes
                up += 1  # Wenn Statistiken existieren, ist das Interface aktiv

        return "ok", f"{up} von {total} Interfaces aktiv", metrics

    def _check_services(self, client: httpx.Client, config: dict) -> tuple[str, str, dict | None]:
        resp = client.get("/core/service/search")
        resp.raise_for_status()
        data = resp.json()

        services = data.get("rows", [])
        watch_list = [s.strip() for s in config.get("services", "").split(",") if s.strip()]

        stopped = []
        metrics = {}
        for svc in services:
            name = svc.get("name", "")
            running = svc.get("running", 0) == 1

            if watch_list and name not in watch_list:
                continue

            metrics[f"opnsense_svc_{name}"] = 1 if running else 0
            if not running and (not watch_list or name in watch_list):
                stopped.append(name)

        if stopped:
            return "critical", f"Services gestoppt: {', '.join(stopped)}", metrics

        checked = len(watch_list) if watch_list else len(services)
        return "ok", f"Alle {checked} Services laufen", metrics
