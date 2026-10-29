# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from typing import Protocol

from app.checkers.agent import AgentPingChecker, AgentResourcesChecker, ServiceProcessChecker
from app.checkers.forecast import DiskForecastChecker
from app.checkers.http import HttpChecker
from app.checkers.ping import PingChecker
from app.checkers.plugins import DockerHealthChecker, ProxmoxBackupChecker, ZfsHealthChecker
from app.checkers.smart import SmartHealthChecker
from app.checkers.system import SystemStateChecker
from app.checkers.tcp import TcpChecker


class Checker(Protocol):
    def run(self, config: dict) -> tuple[str, str, dict | None]:
        """Runs the check.

        Returns:
            (status, message, metrics) where status is "ok"|"warning"|"critical"|"unknown"
        """
        ...


class PushChecker(Checker, Protocol):
    def evaluate(
        self, config: dict, report: dict, prev_details: dict | None = None
    ) -> tuple[str, str, dict | None]:
        """Evaluates a check against the agent's push report.

        `prev_details` is the check's previous `_details` or None; a checker that
        does not need it does not read it.
        """
        ...


# Instantiated once at import. get_checker runs on every scheduled check (hundreds
# per minute at target scale), so the registry must not be rebuilt per call.
_REGISTRY: dict[str, Checker] = {
    "ping": PingChecker(),
    "tcp": TcpChecker(),
    "http": HttpChecker(),
    "agent_ping": AgentPingChecker(),
    "agent_resources": AgentResourcesChecker(),
    "service_process": ServiceProcessChecker(),
    "proxmox_backup": ProxmoxBackupChecker(),
    "zfs_health": ZfsHealthChecker(),
    "docker_health": DockerHealthChecker(),
    "smart_health": SmartHealthChecker(),
    "disk_forecast": DiskForecastChecker(),
    "system_state": SystemStateChecker(),
}


def get_checker(check_type: str) -> Checker:
    """Returns the matching checker for the check_type."""
    checker = _REGISTRY.get(check_type)
    if checker is None:
        raise ValueError(f"Unknown check_type: {check_type!r}")
    return checker
