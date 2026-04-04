"""
Agent-basierte Checker.

Werten Agent-Push-Daten gegen konfigurierbare Thresholds aus.
Die Daten kommen vom srm-monitor-agent via POST /agent/{server_id}/report.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

# In-Memory Map: server_id -> letzter Report-Zeitstempel (Unix)
_last_report: dict[str, float] = {}


def record_agent_report(server_id: str) -> None:
    """Wird beim Agent-Push aufgerufen um den Zeitstempel zu speichern."""
    _last_report[server_id] = time.monotonic()


class AgentPingChecker:
    """Prueft ob der Agent sich innerhalb eines Zeitfensters gemeldet hat.

    Config-Beispiel:
    {
        "stale_minutes": 5
    }

    Dieser Check wird vom Scheduler ausgefuehrt (nicht beim Push).
    Er prüft den letzten Report-Zeitstempel aus der In-Memory-Map.
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
    """Wertet Agent-Ressourcen-Metriken gegen Thresholds aus.

    Config-Beispiel:
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
        # Wird nicht vom Scheduler aufgerufen, sondern direkt bei Agent-Push
        return "unknown", "Wartet auf Agent-Daten", None

    def evaluate(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        """Wertet einen Agent-Report gegen Thresholds aus."""
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

        # Disks
        disk_crit = config.get("disk_crit", 95)
        disk_warn = config.get("disk_warn", 85)
        for disk in resources.get("disks", []):
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

        if problems:
            message = "; ".join(problems)
        else:
            parts = []
            if cpu is not None:
                parts.append(f"CPU {cpu}%")
            if mem is not None:
                parts.append(f"RAM {mem}%")
            message = ", ".join(parts) if parts else "OK"

        return status, message, metrics


class ServiceProcessChecker:
    """Prueft ob Services laufen (basierend auf Agent-Push).

    Zwei Modi:
    - "auto": Erkennt automatisch failed und enabled-but-inactive Units
    - "list": Prueft nur explizit benannte Services (bisheriges Verhalten)

    Config-Beispiel (auto):
    {
        "mode": "auto",
        "ignore": ["ModemManager.service", "udisks2.service"]
    }

    Config-Beispiel (list):
    {
        "mode": "list",
        "services": ["nginx", "docker", "frpc"]
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Wartet auf Agent-Daten", None

    def evaluate(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        """Wertet die Service-Daten aus dem Agent-Report aus."""
        mode = config.get("mode", "list")

        if mode == "auto":
            return self._evaluate_auto(config, report)
        return self._evaluate_list(config, report)

    def _evaluate_auto(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        """Auto-Modus: prueft systemd health aus dem Report."""
        systemd = report.get("systemd")
        if not systemd:
            return "unknown", "Keine systemd-Daten im Report", None

        ignore = set(config.get("ignore", []))

        failed = [u for u in systemd.get("failed", []) if u not in ignore]
        enabled_inactive = [u for u in systemd.get("enabled_inactive", []) if u not in ignore]

        metrics = {
            "services_failed": len(failed),
            "services_enabled_inactive": len(enabled_inactive),
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
        """List-Modus: prueft explizit benannte Services."""
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

        if down:
            return (
                "critical",
                f"Services nicht aktiv: {', '.join(down)}",
                {"services_down": len(down), "services_up": len(up)},
            )

        return (
            "ok",
            f"Alle {len(up)} Services aktiv",
            {"services_down": 0, "services_up": len(up)},
        )
