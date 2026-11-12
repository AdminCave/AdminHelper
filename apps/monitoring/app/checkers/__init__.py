# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.checkers.agent import AgentPingChecker, AgentResourcesChecker, ServiceProcessChecker
from app.checkers.forecast import DiskForecastChecker
from app.checkers.http import HttpChecker
from app.checkers.ping import PingChecker
from app.checkers.plugins import DockerHealthChecker, ProxmoxBackupChecker, ZfsHealthChecker
from app.checkers.probe import ProbeChecker
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


@dataclass(frozen=True)
class PartnerState:
    """The stored state of the agent check paired with a central one (`pair_check_id`).

    `status` is "pending" while the partner has no state yet; `sensor` is the
    partner's probe sensor (tls, certfile, http) as its config names it.
    """

    check_id: str
    sensor: str | None
    status: str
    details: dict | None
    last_check: datetime | None


@dataclass(frozen=True)
class CheckContext:
    """What execute_check hands a checker with `wants_context`: its own previous
    `_details` and, if a valid partner is configured, the partner's state."""

    prev_details: dict | None = None
    partner: PartnerState | None = None


class ContextChecker(Checker, Protocol):
    wants_context: bool

    def run_with_context(self, config: dict, context: CheckContext) -> tuple[str, str, dict | None]:
        """Runs the check like `run`, with what the previous runs and the partner left."""
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
    "probe": ProbeChecker(),
}


def get_checker(check_type: str) -> Checker:
    """Returns the matching checker for the check_type."""
    checker = _REGISTRY.get(check_type)
    if checker is None:
        raise ValueError(f"Unknown check_type: {check_type!r}")
    return checker
