# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent-based checkers.

Evaluate agent push data against configurable thresholds.
The data comes from the adminhelper-agent via POST /agent/{server_id}/report.
"""

from __future__ import annotations

from datetime import datetime

from app.core.time import utcnow_naive

# Pseudo filesystems ignored during disk evaluation
EXCLUDED_FSTYPES = {"", "squashfs", "tmpfs", "devtmpfs", "overlay"}

# In-memory map: server_id -> last report time (naive UTC wall clock). Process-
# local (single-worker invariant, see main.py lifespan); hydrated at startup
# from monitor_agent_liveness so a restart no longer makes agent_ping fall back
# to 'unknown' until the next push. Wall clock instead of time.monotonic on
# purpose — a monotonic value cannot be persisted across processes.
_last_report: dict[str, datetime] = {}


def record_agent_report(server_id: str) -> None:
    """Called on agent push to store the timestamp."""
    _last_report[server_id] = utcnow_naive()


def hydrate_agent_liveness(entries: dict[str, datetime]) -> None:
    """Seed _last_report from the persisted monitor_agent_liveness rows at
    startup. setdefault: a push that arrived before hydration must not be
    overwritten by an older persisted value."""
    for server_id, last_report_at in entries.items():
        _last_report.setdefault(server_id, last_report_at)


class AgentPingChecker:
    """Checks whether the agent has reported within a time window.

    Config example:
    {
        "stale_minutes": 15
    }

    This check is run by the scheduler (not on push).
    It checks the last report timestamp from the in-memory map.
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        server_id = config.get("server_id", "")
        # Default 15 = three missed 5-minute push intervals. The old default of
        # 5 equalled the agent's push cadence and flagged a single late report
        # as critical.
        stale_minutes = config.get("stale_minutes", 15)

        if not server_id:
            return "unknown", "Keine server_id konfiguriert", None

        last = _last_report.get(server_id)
        if last is None:
            return "unknown", "Noch kein Agent-Report empfangen", None

        age_seconds = (utcnow_naive() - last).total_seconds()
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


def _grade(
    value: float,
    warn: float,
    crit: float,
    label: str,
    unit: str,
    problems: list[str],
    status: str,
) -> str:
    """Escalate `status` for one threshold measurement: >= crit -> critical, >= warn
    -> warning (never downgrading an already-critical status). Appends the breached
    `label` plus the crossed threshold to `problems`. Shared by the CPU/RAM/disk/
    temperature checks so the escalation rule lives in one place (2.31)."""
    if value >= crit:
        problems.append(f"{label} (>={crit}{unit})")
        return "critical"
    if value >= warn:
        problems.append(f"{label} (>={warn}{unit})")
        return "critical" if status == "critical" else "warning"
    return status


class AgentResourcesChecker:
    """Evaluates agent resource metrics against thresholds.

    Config example:
    {
        "cpu_warn": 80,
        "cpu_crit": 95,
        "memory_warn": 80,
        "memory_crit": 95,
        "disk_warn": 85,
        "disk_crit": 95
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
            status = _grade(cpu, cpu_warn, cpu_crit, f"CPU {cpu}%", "%", problems, status)

        # Memory
        mem = resources.get("memory_percent")
        if mem is not None:
            metrics["agent_memory_percent"] = mem
            mem_crit = config.get("memory_crit", 95)
            mem_warn = config.get("memory_warn", 80)
            status = _grade(mem, mem_warn, mem_crit, f"RAM {mem}%", "%", problems, status)

        # Disks — filter pseudo filesystems server-side
        # Old agents send no fstype → default "_real_" passes the filter
        raw_disks = resources.get("disks", [])
        disks = [d for d in raw_disks if d.get("fstype", "_real_") not in EXCLUDED_FSTYPES]

        disk_crit = config.get("disk_crit", 95)
        disk_warn = config.get("disk_warn", 85)
        for disk in disks:
            pct = disk.get("percent", 0)
            mount = disk.get("mount", "?")
            # No per-mount metric: the agent router already writes monitor_agent_disk_percent
            # dimensionally (mount tag). Encoding the mount into the metric NAME here was a
            # duplicate series in a second schema (1.18); the value is still graded below.
            status = _grade(
                pct, disk_warn, disk_crit, f"Disk {mount} {pct}%", "%", problems, status
            )

        # Temperatures (optional — VMs provide no sensor data)
        temperatures = resources.get("temperatures", [])
        if temperatures:
            temp_crit = config.get("temp_crit", 95)
            temp_warn = config.get("temp_warn", 80)
            temp_overrides = config.get("temp_overrides", {})
            for sensor in temperatures:
                temp_c = sensor.get("temp_c", 0)
                sensor_name = sensor.get("sensor", "?")
                # Same as disks: the router writes monitor_agent_temp dimensionally (sensor
                # tag); the name-encoded copy here was the duplicate (1.18). Still graded below.
                ov = temp_overrides.get(sensor_name, {})
                s_crit = ov.get("crit", temp_crit)
                s_warn = ov.get("warn", temp_warn)
                status = _grade(
                    temp_c,
                    s_warn,
                    s_crit,
                    f"Temp {sensor_name} {temp_c}\u00b0C",
                    "\u00b0C",
                    problems,
                    status,
                )

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
                {
                    "mount": d.get("mount", "/"),
                    "percent": d.get("percent", 0),
                    "total_gb": d.get("total_gb"),
                    "used_gb": d.get("used_gb"),
                }
                for d in disks
            ],
            "temperatures": [
                {
                    "sensor": s.get("sensor", "?"),
                    "temp_c": s.get("temp_c", 0),
                    "high": s.get("high", 0),
                    "critical": s.get("critical", 0),
                }
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

        The key-presence check below is load-bearing: v2 agents throttle the
        large, mostly-static all_services inventory and OMIT the key on most
        pushes, while failed/enabled_inactive are always sent — a missing key
        means "fall back to the legacy keys", only an empty list means
        "genuinely no services". The inventory is not persisted server-side,
        so nothing is lost by a throttled push.
        """
        systemd = report.get("systemd")
        if not systemd:
            return "unknown", "Keine systemd-Daten im Report", None

        ignore = self._parse_ignore(config.get("ignore", []))

        if "all_services" in systemd:
            # New format: raw data from agent, server filters. Cap the inventory length
            # so a huge/hostile all_services array can't drive a DoS (3.76); a non-list
            # value is treated as empty.
            raw_all = systemd["all_services"]
            all_svcs = raw_all[:500] if isinstance(raw_all, list) else []
            failed_raw = [s["unit"] for s in all_svcs if s.get("active_state") == "failed"]
            enabled_inactive_raw = [
                s["unit"]
                for s in all_svcs
                if s.get("enabled_state") == "enabled" and s.get("active_state") == "inactive"
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
