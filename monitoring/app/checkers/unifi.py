"""
Unifi Controller Checker — Device-Status, Client-Count.

Config-Parameter:
  credential_id: ID des Unifi-Credentials (Typ: unifi_login)
  host: Unifi Controller Host (IP/Hostname)
  port: Port (default 443)
  site: Site-Name (default "default")
  verify_ssl: SSL verifizieren (default false)
  check_mode: "devices" (default), "clients"
  device_mac: MAC-Adresse eines bestimmten Geraets (optional, fuer Einzel-Check)

Unifi-Login Credential Config:
  username: Controller-Benutzername
  password: Controller-Passwort
"""

from __future__ import annotations

import json
import logging

import httpx

logger = logging.getLogger("monitor.checker.unifi")


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


class UnifiDeviceChecker:
    """Prueft Unifi-Geraete via Controller API."""

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        cred_id = config.get("credential_id", "")
        if not cred_id:
            return "unknown", "Kein credential_id konfiguriert", None

        cred = _load_credential(cred_id)
        username = cred.get("username", "")
        password = cred.get("password", "")
        if not username or not password:
            return "unknown", "Unifi-Login unvollstaendig", None

        host = config.get("host", "")
        port = int(config.get("port", 443))
        site = config.get("site", "default")
        verify = config.get("verify_ssl", False)
        check_mode = config.get("check_mode", "devices")

        if not host:
            return "unknown", "Kein Host angegeben", None

        base_url = f"https://{host}:{port}"
        client = httpx.Client(base_url=base_url, verify=verify, timeout=15)

        try:
            # Login
            login_resp = client.post("/api/login", json={
                "username": username,
                "password": password,
            })
            if login_resp.status_code not in (200, 302):
                # Neues UniFi OS Format
                login_resp = client.post("/api/auth/login", json={
                    "username": username,
                    "password": password,
                })
            if login_resp.status_code not in (200, 302):
                return "critical", f"Login fehlgeschlagen: HTTP {login_resp.status_code}", None

            if check_mode == "clients":
                return self._check_clients(client, site, config)
            else:
                return self._check_devices(client, site, config)

        except Exception as e:
            return "critical", f"Verbindungsfehler: {e}", None
        finally:
            try:
                client.post("/api/logout")
            except Exception:
                pass
            client.close()

    def _check_devices(self, client: httpx.Client, site: str, config: dict) -> tuple[str, str, dict | None]:
        # Versuche beide API-Pfade (Legacy vs UniFi OS)
        resp = client.get(f"/api/s/{site}/stat/device")
        if resp.status_code == 401 or resp.status_code == 404:
            resp = client.get(f"/proxy/network/api/s/{site}/stat/device")
        resp.raise_for_status()

        devices = resp.json().get("data", [])
        target_mac = config.get("device_mac", "").lower().strip()

        metrics = {}
        offline = []
        total = 0

        for dev in devices:
            mac = dev.get("mac", "").lower()
            name = dev.get("name", dev.get("model", mac))
            state = dev.get("state", 0)  # 1 = connected
            adopted = dev.get("adopted", False)

            if target_mac and mac != target_mac:
                continue

            total += 1
            is_online = state == 1 and adopted

            metrics[f"unifi_device_{mac.replace(':', '')}"] = 1 if is_online else 0

            if dev.get("system-stats"):
                cpu = dev["system-stats"].get("cpu", "0")
                mem = dev["system-stats"].get("mem", "0")
                try:
                    metrics[f"unifi_device_cpu_{mac.replace(':', '')}"] = float(cpu)
                    metrics[f"unifi_device_mem_{mac.replace(':', '')}"] = float(mem)
                except (ValueError, TypeError):
                    pass

            if not is_online:
                offline.append(name)

        if target_mac and total == 0:
            return "unknown", f"Geraet {target_mac} nicht gefunden", None

        if offline:
            return "critical", f"Offline: {', '.join(offline)} ({len(offline)} von {total})", metrics

        return "ok", f"Alle {total} Geraete online", metrics

    def _check_clients(self, client: httpx.Client, site: str, config: dict) -> tuple[str, str, dict | None]:
        resp = client.get(f"/api/s/{site}/stat/sta")
        if resp.status_code == 401 or resp.status_code == 404:
            resp = client.get(f"/proxy/network/api/s/{site}/stat/sta")
        resp.raise_for_status()

        clients = resp.json().get("data", [])
        wired = sum(1 for c in clients if not c.get("is_wired", True) is False)
        wireless = len(clients) - wired

        metrics = {
            "unifi_clients_total": len(clients),
            "unifi_clients_wired": wired,
            "unifi_clients_wireless": wireless,
        }

        min_clients = int(config.get("min_clients", 0))
        max_clients = int(config.get("max_clients", 0))

        if min_clients and len(clients) < min_clients:
            return "warning", f"Nur {len(clients)} Clients (erwartet min. {min_clients})", metrics
        if max_clients and len(clients) > max_clients:
            return "warning", f"{len(clients)} Clients (erwartet max. {max_clients})", metrics

        return "ok", f"{len(clients)} Clients ({wireless} WiFi, {wired} LAN)", metrics
