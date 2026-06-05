# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent-based checkers.

Evaluate agent push data against configurable thresholds.
The data comes from the adminhelper-agent via POST /agent/{server_id}/report.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

# Pseudo filesystems ignored during disk evaluation
EXCLUDED_FSTYPES = {"", "squashfs", "tmpfs", "devtmpfs", "overlay"}

# In-memory map: server_id -> last report timestamp (Unix)
_last_report: dict[str, float] = {}


def record_agent_report(server_id: str) -> None:
    """Called on agent push to store the timestamp."""
    _last_report[server_id] = time.monotonic()


class AgentPingChecker:
    """Checks whether the agent has reported within a time window.

    Config example:
    {
        "stale_minutes": 5
    }

    This check is run by the scheduler (not on push).
    It checks the last report timestamp from the in-memory map.
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        server_id = config.get("server_id", "")
        stale_minutes = config.get("stale_minutes", 5)

        if not server_id:
            return "unknown", "Keine server_id konfiguriert", None

        last = _last_report.get(server_id)
        if last is None:
            return "unknown", "Noch kein Agent-Report empfangen", None

        age_seconds = time.monotonic() - last
        age_minutes = age_seconds / 60

        if age_minutes > stale_minutes:
            return (
                "critical",
                f"Agent seit {age_minutes:.0f} Min. nicht erreichbar (Limit: {stale_minutes} Min.)",
                {"agent_last_seen_seconds": round(age_seconds)},
            )

        return (
            "ok",
            f"Agent aktiv (letzter Report vor {age_seconds:.0f}s)",
            {"agent_last_seen_seconds": round(age_seconds)},
        )


class AgentResourcesChecker:
    """Evaluates agent resource metrics against thresholds.

    Config example:
    {
        "cpu_warn": 80,
        "cpu_crit": 95,
        "memory_warn": 80,
        "memory_crit": 95,
        "disk_warn": 85,
        "disk_crit": 95,
        "stale_minutes": 5
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        # Not called by the scheduler, but directly on agent push
        return "unknown", "Wartet auf Agent-Daten", None

    def evaluate(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        """Evaluates an agent report against thresholds."""
        resources = report.get("resources", {})
        if not resources:
            return "unknown", "Keine Ressourcen-Daten", None

        problems = []
        status = "ok"
        metrics = {}

        # CPU
        cpu = resources.get("cpu_percent")
        if cpu is not None:
            metrics["agent_cpu_percent"] = cpu
            cpu_crit = config.get("cpu_crit", 95)
            cpu_warn = config.get("cpu_warn", 80)
            if cpu >= cpu_crit:
                problems.append(f"CPU {cpu}% (>={cpu_crit}%)")
                status = "critical"
            elif cpu >= cpu_warn:
                problems.append(f"CPU {cpu}% (>={cpu_warn}%)")
                if status != "critical":
                    status = "warning"

        # Memory
        mem = resources.get("memory_percent")
        if mem is not None:
            metrics["agent_memory_percent"] = mem
            mem_crit = config.get("memory_crit", 95)
            mem_warn = config.get("memory_warn", 80)
            if mem >= mem_crit:
                problems.append(f"RAM {mem}% (>={mem_crit}%)")
                status = "critical"
            elif mem >= mem_warn:
                problems.append(f"RAM {mem}% (>={mem_warn}%)")
                if status != "critical":
                    status = "warning"

        # Disks — filter pseudo filesystems server-side
        # Old agents send no fstype → default "_real_" passes the filter
        raw_disks = resources.get("disks", [])
        disks = [d for d in raw_disks if d.get("fstype", "_real_") not in EXCLUDED_FSTYPES]

        disk_crit = config.get("disk_crit", 95)
        disk_warn = config.get("disk_warn", 85)
        for disk in disks:
            pct = disk.get("percent", 0)
            mount = disk.get("mount", "?")
            metrics[f"agent_disk_percent_{mount}"] = pct
            if pct >= disk_crit:
                problems.append(f"Disk {mount} {pct}% (>={disk_crit}%)")
                status = "critical"
            elif pct >= disk_warn:
                problems.append(f"Disk {mount} {pct}% (>={disk_warn}%)")
                if status != "critical":
                    status = "warning"

        # Temperatures (optional — VMs provide no sensor data)
        temperatures = resources.get("temperatures", [])
        if temperatures:
            temp_crit = config.get("temp_crit", 95)
            temp_warn = config.get("temp_warn", 80)
            temp_overrides = config.get("temp_overrides", {})
            for sensor in temperatures:
                temp_c = sensor.get("temp_c", 0)
                sensor_name = sensor.get("sensor", "?")
                metrics[f"agent_temp_{sensor_name}"] = temp_c
                ov = temp_overrides.get(sensor_name, {})
                s_crit = ov.get("crit", temp_crit)
                s_warn = ov.get("warn", temp_warn)
                if temp_c >= s_crit:
                    problems.append(f"Temp {sensor_name} {temp_c}\u00b0C (>={s_crit}\u00b0C)")
                    status = "critical"
                elif temp_c >= s_warn:
                    problems.append(f"Temp {sensor_name} {temp_c}\u00b0C (>={s_warn}\u00b0C)")
                    if status != "critical":
                        status = "warning"

        if problems:
            message = "; ".join(problems)
        else:
            parts = []
            if cpu is not None:
                parts.append(f"CPU {cpu}%")
            if mem is not None:
                parts.append(f"RAM {mem}%")
            message = ", ".join(parts) if parts else "OK"

        metrics["_details"] = {
            "cpu": cpu,
            "memory": mem,
            "memory_total_mb": resources.get("memory_total_mb"),
            "memory_used_mb": resources.get("memory_used_mb"),
            "disks": [
                {"mount": d.get("mount", "/"), "percent": d.get("percent", 0),
                 "total_gb": d.get("total_gb"), "used_gb": d.get("used_gb")}
                for d in disks
            ],
            "temperatures": [
                {"sensor": s.get("sensor", "?"), "temp_c": s.get("temp_c", 0),
                 "high": s.get("high", 0), "critical": s.get("critical", 0)}
                for s in temperatures
            ],
        }

        return status, message, metrics


class ServiceProcessChecker:
    """Checks whether services are running (based on agent push).

    Two modes:
    - "auto": Automatically detects failed and enabled-but-inactive units
    - "list": Only checks explicitly named services (previous behavior)

    Config example (auto):
    {
        "mode": "auto",
        "ignore": ["ModemManager.service", "udisks2.service"]
    }

    Config example (list):
    {
        "mode": "list",
        "services": ["nginx", "docker", "frpc"]
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Wartet auf Agent-Daten", None

    def evaluate(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        """Evaluates the service data from the agent report."""
        mode = config.get("mode", "list")

        if mode == "auto":
            return self._evaluate_auto(config, report)
        return self._evaluate_list(config, report)

    @staticmethod
    def _parse_ignore(raw) -> set:
        """Normalizes the ignore list: accepts an array or a CSV string."""
        if isinstance(raw, str):
            return {s.strip() for s in raw.split(",") if s.strip()}
        if isinstance(raw, list):
            result = set()
            for item in raw:
                if isinstance(item, str) and "," in item:
                    result.update(s.strip() for s in item.split(",") if s.strip())
                elif isinstance(item, str) and item.strip():
                    result.add(item.strip())
            return result
        return set()

    @staticmethod
    def _is_ignored(unit: str, ignore: set) -> bool:
        """Checks whether a unit should be ignored (with/without .service suffix)."""
        if unit in ignore:
            return True
        # "nginx" should also match "nginx.service" and vice versa
        if unit.endswith(".service"):
            return unit[:-8] in ignore
        return f"{unit}.service" in ignore

    def _evaluate_auto(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        """Auto mode: checks systemd health from the report.

        Supports two report formats:
        - New (v2): systemd.all_services with raw data → server filters itself
        - Old (v1): systemd.failed / systemd.enabled_inactive (agent pre-filtered)
        """
        systemd = report.get("systemd")
        if not systemd:
            return "unknown", "Keine systemd-Daten im Report", None

        ignore = self._parse_ignore(config.get("ignore", []))

        if "all_services" in systemd:
            # New format: raw data from agent, server filters
            all_svcs = systemd["all_services"]
            failed_raw = [s["unit"] for s in all_svcs if s.get("active_state") == "failed"]
            enabled_inactive_raw = [
                s["unit"] for s in all_svcs
                if s.get("enabled_state") == "enabled"
                and s.get("active_state") == "inactive"
            ]
            # Also include non-service failed units (e.g. .mount, .socket)
            for u in systemd.get("failed", []):
                if u not in failed_raw:
                    failed_raw.append(u)
        else:
            # Old format: agent has already filtered
            failed_raw = systemd.get("failed", [])
            enabled_inactive_raw = systemd.get("enabled_inactive", [])

        failed = [u for u in failed_raw if not self._is_ignored(u, ignore)]
        enabled_inactive = [u for u in enabled_inactive_raw if not self._is_ignored(u, ignore)]

        metrics = {
            "services_failed": len(failed),
            "services_enabled_inactive": len(enabled_inactive),
        }

        metrics["_details"] = {
            "mode": "auto",
            "failed": failed,
            "enabled_inactive": enabled_inactive,
        }

        if failed:
            msg = f"Failed: {', '.join(failed)}"
            if enabled_inactive:
                msg += f"; Inaktiv (autostart): {', '.join(enabled_inactive)}"
            return "critical", msg, metrics

        if enabled_inactive:
            return (
                "warning",
                f"Inaktiv (autostart): {', '.join(enabled_inactive)}",
                metrics,
            )

        return "ok", "Alle systemd-Units OK", metrics

    def _evaluate_list(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        """List mode: checks explicitly named services."""
        expected = config.get("services", [])
        if not expected:
            return "ok", "Keine Services konfiguriert", None

        reported = {s["name"]: s for s in report.get("services", [])}
        down = []
        up = []

        for name in expected:
            svc = reported.get(name)
            if svc and svc.get("running"):
                up.append(name)
            else:
                down.append(name)

        metrics = {"services_down": len(down), "services_up": len(up)}
        metrics["_details"] = {
            "mode": "list",
            "watched": [{"name": n, "running": n not in down} for n in expected],
        }

        if down:
            return (
                "critical",
                f"Services nicht aktiv: {', '.join(down)}",
                metrics,
            )

        return (
            "ok",
            f"Alle {len(up)} Services aktiv",
            metrics,
        )
