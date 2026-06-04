# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from typing import Protocol


class Checker(Protocol):
    def run(self, config: dict) -> tuple[str, str, dict | None]:
        """Runs the check.

        Returns:
            (status, message, metrics) where status is "ok"|"warning"|"critical"|"unknown"
        """
        ...


def get_checker(check_type: str) -> Checker:
    """Returns the matching checker for the check_type."""
    from app.checkers.ping import PingChecker
    from app.checkers.tcp import TcpChecker
    from app.checkers.http import HttpChecker
    from app.checkers.agent import AgentPingChecker, AgentResourcesChecker, ServiceProcessChecker
    from app.checkers.plugins import ProxmoxBackupChecker, ZfsHealthChecker, DockerHealthChecker
    from app.checkers.smart import SmartHealthChecker

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
    }

    checker = _REGISTRY.get(check_type)
    if checker is None:
        raise ValueError(f"Unbekannter check_type: {check_type!r}")
    return checker
