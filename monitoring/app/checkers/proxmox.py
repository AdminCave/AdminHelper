"""
Proxmox VE + Proxmox Backup Server Checker.

Check-Types:
  - proxmox_node: Node-Status (CPU, RAM, Uptime, Services)
  - proxmox_vm: VM/LXC-Status (running, stopped, CPU, RAM)
  - pbs_job: Backup-Job-Status (letzter Backup, Alter, Datastore-Usage)

Config-Parameter (alle):
  credential_id: ID des Proxmox-Credentials (Typ: proxmox_token)
  host: Proxmox-Host (IP/Hostname)
  port: API-Port (default 8006 fuer PVE, 8007 fuer PBS)
  verify_ssl: SSL verifizieren (default false)

Proxmox-Token Credential Config:
  token_id: z.B. "root@pam!monitoring"
  token_secret: UUID-Token-Secret
"""

from __future__ import annotations

import json
import logging
import time

import httpx

logger = logging.getLogger("monitor.checker.proxmox")


def _load_credential(credential_id: str) -> dict:
    """Laedt Credential aus der DB."""
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


def _pve_client(config: dict) -> tuple[httpx.Client, dict]:
    """Erstellt einen httpx-Client mit Proxmox-Auth-Header."""
    cred_id = config.get("credential_id", "")
    if not cred_id:
        raise ValueError("Kein credential_id konfiguriert")

    cred = _load_credential(cred_id)
    token_id = cred.get("token_id", "")
    token_secret = cred.get("token_secret", "")
    if not token_id or not token_secret:
        raise ValueError("Proxmox-Token unvollstaendig (token_id/token_secret)")

    host = config.get("host", "")
    port = int(config.get("port", 8006))
    verify = config.get("verify_ssl", False)

    base_url = f"https://{host}:{port}/api2/json"
    headers = {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}

    client = httpx.Client(base_url=base_url, headers=headers, verify=verify, timeout=10)
    return client, {"host": host}


class ProxmoxNodeChecker:
    """Prueft Proxmox VE Node-Status."""

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        node = config.get("node", "")
        if not node:
            return "unknown", "Kein node angegeben", None

        try:
            client, info = _pve_client(config)
        except ValueError as e:
            return "unknown", str(e), None

        try:
            resp = client.get(f"/nodes/{node}/status")
            resp.raise_for_status()
            data = resp.json().get("data", {})

            cpu = round(data.get("cpu", 0) * 100, 1)
            mem_used = data.get("memory", {}).get("used", 0)
            mem_total = data.get("memory", {}).get("total", 1)
            mem_pct = round(mem_used / mem_total * 100, 1) if mem_total else 0
            uptime = data.get("uptime", 0)

            metrics = {
                "proxmox_node_cpu": cpu,
                "proxmox_node_memory_percent": mem_pct,
                "proxmox_node_uptime": uptime,
            }

            # Threshold-Auswertung
            cpu_crit = float(config.get("cpu_crit", 95))
            cpu_warn = float(config.get("cpu_warn", 85))
            mem_crit = float(config.get("mem_crit", 95))
            mem_warn = float(config.get("mem_warn", 85))

            if cpu >= cpu_crit or mem_pct >= mem_crit:
                status = "critical"
            elif cpu >= cpu_warn or mem_pct >= mem_warn:
                status = "warning"
            else:
                status = "ok"

            message = f"Node {node}: CPU {cpu}%, RAM {mem_pct}%, Up {uptime // 3600}h"
            return status, message, metrics

        except httpx.HTTPStatusError as e:
            return "critical", f"API-Fehler: HTTP {e.response.status_code}", None
        except Exception as e:
            return "critical", f"Verbindungsfehler: {e}", None
        finally:
            client.close()


class ProxmoxVmChecker:
    """Prueft Proxmox VM/LXC Status."""

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        node = config.get("node", "")
        vmid = config.get("vmid", "")
        vm_type = config.get("vm_type", "qemu")  # qemu oder lxc

        if not node or not vmid:
            return "unknown", "node und vmid erforderlich", None

        try:
            client, info = _pve_client(config)
        except ValueError as e:
            return "unknown", str(e), None

        try:
            resp = client.get(f"/nodes/{node}/{vm_type}/{vmid}/status/current")
            resp.raise_for_status()
            data = resp.json().get("data", {})

            vm_status = data.get("status", "unknown")
            name = data.get("name", vmid)
            cpu = round(data.get("cpu", 0) * 100, 1)
            mem_used = data.get("mem", 0)
            mem_total = data.get("maxmem", 1)
            mem_pct = round(mem_used / mem_total * 100, 1) if mem_total else 0

            metrics = {
                "proxmox_vm_status": 1 if vm_status == "running" else 0,
                "proxmox_vm_cpu": cpu,
                "proxmox_vm_memory_percent": mem_pct,
            }

            expected = config.get("expected_status", "running")
            if vm_status != expected:
                return "critical", f"{name} ({vmid}): {vm_status} (erwartet: {expected})", metrics

            return "ok", f"{name} ({vmid}): {vm_status}, CPU {cpu}%, RAM {mem_pct}%", metrics

        except httpx.HTTPStatusError as e:
            return "critical", f"API-Fehler: HTTP {e.response.status_code}", None
        except Exception as e:
            return "critical", f"Verbindungsfehler: {e}", None
        finally:
            client.close()


class PbsJobChecker:
    """Prueft Proxmox Backup Server — letzter Backup-Job, Datastore-Usage."""

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        datastore = config.get("datastore", "")
        if not datastore:
            return "unknown", "Kein datastore angegeben", None

        try:
            cred_id = config.get("credential_id", "")
            if not cred_id:
                return "unknown", "Kein credential_id konfiguriert", None

            cred = _load_credential(cred_id)
            token_id = cred.get("token_id", "")
            token_secret = cred.get("token_secret", "")
            if not token_id or not token_secret:
                return "unknown", "PBS-Token unvollstaendig", None

            host = config.get("host", "")
            port = int(config.get("port", 8007))
            verify = config.get("verify_ssl", False)

            base_url = f"https://{host}:{port}/api2/json"
            headers = {"Authorization": f"PBSAPIToken={token_id}:{token_secret}"}

            client = httpx.Client(base_url=base_url, headers=headers, verify=verify, timeout=10)
        except Exception as e:
            return "unknown", f"Client-Fehler: {e}", None

        try:
            # Datastore-Usage
            resp = client.get(f"/admin/datastore/{datastore}/status")
            resp.raise_for_status()
            ds_data = resp.json().get("data", {})

            used = ds_data.get("used", 0)
            total = ds_data.get("total", 1)
            usage_pct = round(used / total * 100, 1) if total else 0

            # Letzter Snapshot-Zeitpunkt
            snap_resp = client.get(f"/admin/datastore/{datastore}/snapshots")
            snap_resp.raise_for_status()
            snapshots = snap_resp.json().get("data", [])

            metrics = {
                "pbs_datastore_usage_percent": usage_pct,
            }

            if snapshots:
                latest_time = max(s.get("backup-time", 0) for s in snapshots)
                age_hours = round((time.time() - latest_time) / 3600, 1)
                metrics["pbs_last_backup_age_hours"] = age_hours

                max_age = float(config.get("max_backup_age_hours", 26))
                disk_crit = float(config.get("disk_crit", 90))
                disk_warn = float(config.get("disk_warn", 80))

                if age_hours > max_age:
                    return "critical", f"Letzter Backup vor {age_hours}h (max {max_age}h), Disk {usage_pct}%", metrics
                if usage_pct >= disk_crit:
                    return "critical", f"Datastore {usage_pct}% voll, Backup {age_hours}h alt", metrics
                if usage_pct >= disk_warn:
                    return "warning", f"Datastore {usage_pct}% voll, Backup {age_hours}h alt", metrics

                return "ok", f"Datastore {usage_pct}%, letzter Backup vor {age_hours}h", metrics
            else:
                return "warning", f"Keine Snapshots in {datastore}, Disk {usage_pct}%", metrics

        except httpx.HTTPStatusError as e:
            return "critical", f"API-Fehler: HTTP {e.response.status_code}", None
        except Exception as e:
            return "critical", f"Verbindungsfehler: {e}", None
        finally:
            client.close()
