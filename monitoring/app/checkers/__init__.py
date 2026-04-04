from __future__ import annotations

from typing import Protocol


class Checker(Protocol):
    def run(self, config: dict) -> tuple[str, str, dict | None]:
        """Fuehrt den Check aus.

        Returns:
            (status, message, metrics) wobei status "ok"|"warning"|"critical"|"unknown"
        """
        ...


def get_checker(check_type: str) -> Checker:
    """Gibt den passenden Checker fuer den check_type zurueck."""
    from app.checkers.ping import PingChecker
    from app.checkers.tcp import TcpChecker
    from app.checkers.http import HttpChecker
    from app.checkers.agent import AgentResourcesChecker, ServiceProcessChecker
    from app.checkers.snmp import SnmpChecker
    from app.checkers.proxmox import ProxmoxNodeChecker, ProxmoxVmChecker, PbsJobChecker
    from app.checkers.opnsense import OpnsenseChecker
    from app.checkers.unifi import UnifiDeviceChecker

    _REGISTRY: dict[str, Checker] = {
        "ping": PingChecker(),
        "tcp": TcpChecker(),
        "http": HttpChecker(),
        "agent_resources": AgentResourcesChecker(),
        "service_process": ServiceProcessChecker(),
        "snmp": SnmpChecker(),
        "proxmox_node": ProxmoxNodeChecker(),
        "proxmox_vm": ProxmoxVmChecker(),
        "pbs_job": PbsJobChecker(),
        "opnsense": OpnsenseChecker(),
        "unifi_device": UnifiDeviceChecker(),
    }

    checker = _REGISTRY.get(check_type)
    if checker is None:
        raise ValueError(f"Unbekannter check_type: {check_type!r}")
    return checker
