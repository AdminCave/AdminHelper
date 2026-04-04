"""
Plugin-basierte Checker.

Werten Agent-Push-Daten von automatisch erkannten Plugins aus
(Proxmox, ZFS, Docker). Die Daten kommen vom srm-monitor-agent,
der die Plugins anhand installierter Binaries aktiviert.
"""

from __future__ import annotations

import time


class ProxmoxBackupChecker:
    """Prueft ob VMs/CTs aktuelle Backups haben.

    Config-Beispiel:
    {
        "max_backup_age_hours": 26,
        "exclude_vmids": [999],
        "exclude_stopped": true
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Wartet auf Agent-Daten", None

    def evaluate(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        proxmox = report.get("proxmox")
        if not proxmox:
            return "unknown", "Keine Proxmox-Daten im Report", None

        vms = proxmox.get("vms", [])
        if not vms:
            return "ok", "Keine VMs/CTs gefunden", None

        max_age_hours = config.get("max_backup_age_hours", 26)
        exclude_vmids = set(config.get("exclude_vmids", []))
        exclude_stopped = config.get("exclude_stopped", True)
        max_age_seconds = max_age_hours * 3600
        now = time.time()

        no_backup = []
        outdated = []
        ok_count = 0

        for vm in vms:
            vmid = vm.get("vmid")
            if vmid in exclude_vmids:
                continue
            if exclude_stopped and vm.get("status") != "running":
                continue

            label = f"{vm.get('type', 'vm').upper()} {vmid} ({vm.get('name', '?')})"
            last_ts = vm.get("last_backup_ts")

            if last_ts is None:
                no_backup.append(label)
            elif (now - last_ts) > max_age_seconds:
                age_h = round((now - last_ts) / 3600)
                outdated.append(f"{label}: {age_h}h alt")
            else:
                ok_count += 1

        metrics = {
            "proxmox_backup_ok": ok_count,
            "proxmox_backup_missing": len(no_backup),
            "proxmox_backup_outdated": len(outdated),
        }

        if no_backup:
            msg = "Kein Backup: " + ", ".join(no_backup)
            if outdated:
                msg += "; Veraltet: " + ", ".join(outdated)
            return "critical", msg, metrics

        if outdated:
            return "warning", "Veraltete Backups: " + ", ".join(outdated), metrics

        return "ok", f"Alle {ok_count} VMs/CTs haben aktuelle Backups", metrics


class ZfsHealthChecker:
    """Prueft ZFS Pool Health und Kapazitaet.

    Config-Beispiel:
    {
        "capacity_warn": 80,
        "capacity_crit": 90
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Wartet auf Agent-Daten", None

    def evaluate(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        zfs = report.get("zfs")
        if not zfs:
            return "unknown", "Keine ZFS-Daten im Report", None

        pools = zfs.get("pools", [])
        if not pools:
            return "ok", "Keine ZFS-Pools gefunden", None

        cap_warn = config.get("capacity_warn", 80)
        cap_crit = config.get("capacity_crit", 90)

        status = "ok"
        problems = []
        metrics = {}

        for pool in pools:
            name = pool.get("name", "?")
            health = pool.get("health", "UNKNOWN")
            cap = pool.get("capacity_percent", 0)
            metrics[f"zfs_capacity_{name}"] = cap

            if health in ("FAULTED", "OFFLINE", "UNAVAIL"):
                problems.append(f"{name}: {health}")
                status = "critical"
            elif health == "DEGRADED":
                problems.append(f"{name}: DEGRADED")
                if status != "critical":
                    status = "warning"

            if cap >= cap_crit:
                problems.append(f"{name}: {cap}% voll (>={cap_crit}%)")
                status = "critical"
            elif cap >= cap_warn:
                problems.append(f"{name}: {cap}% voll (>={cap_warn}%)")
                if status != "critical":
                    status = "warning"

        if problems:
            return status, "; ".join(problems), metrics

        pool_summary = ", ".join(f"{p['name']} {p.get('capacity_percent', 0)}%" for p in pools)
        return "ok", f"Alle Pools ONLINE: {pool_summary}", metrics


class DockerHealthChecker:
    """Prueft Docker Container Status.

    Config-Beispiel:
    {
        "ignore_containers": ["watchtower"],
        "check_restarts": true
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Wartet auf Agent-Daten", None

    def evaluate(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        docker = report.get("docker")
        if not docker:
            return "unknown", "Keine Docker-Daten im Report", None

        containers = docker.get("containers", [])
        if not containers:
            return "ok", "Keine Container gefunden", None

        ignore = set(config.get("ignore_containers", []))

        critical_problems = []
        warning_problems = []
        ok_count = 0

        for c in containers:
            name = c.get("name", c.get("id", "?"))
            if name in ignore:
                continue

            state = c.get("state", "").lower()
            status_text = c.get("status", "").lower()
            restart_policy = c.get("restart_policy", "no")

            # Container mit Restart-Policy die nicht laufen
            if restart_policy not in ("no", "") and state != "running":
                if state in ("dead", "restarting"):
                    critical_problems.append(f"{name}: {state}")
                else:
                    critical_problems.append(f"{name}: nicht aktiv (policy={restart_policy})")
                continue

            # Unhealthy Container
            if "unhealthy" in status_text:
                warning_problems.append(f"{name}: unhealthy")
                continue

            if state == "running":
                ok_count += 1

        metrics = {
            "docker_ok": ok_count,
            "docker_critical": len(critical_problems),
            "docker_warning": len(warning_problems),
        }

        if critical_problems:
            msg = "Container-Probleme: " + ", ".join(critical_problems)
            if warning_problems:
                msg += "; Warnung: " + ", ".join(warning_problems)
            return "critical", msg, metrics

        if warning_problems:
            return "warning", "Container-Warnungen: " + ", ".join(warning_problems), metrics

        return "ok", f"Alle {ok_count} Container laufen", metrics
