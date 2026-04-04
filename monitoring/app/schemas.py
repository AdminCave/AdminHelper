from __future__ import annotations

from pydantic import BaseModel


class CheckCreate(BaseModel):
    server_id: str | None = None
    name: str
    description: str | None = None
    check_type: str
    config: dict = {}
    enabled: bool = True
    interval: str = "5m"
    severity: str = "critical"
    consecutive_fails: int = 3


class CheckUpdate(BaseModel):
    server_id: str | None = None
    name: str | None = None
    description: str | None = None
    check_type: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    interval: str | None = None
    severity: str | None = None
    consecutive_fails: int | None = None


VALID_CHECK_TYPES = {
    "ping",
    "tcp",
    "http",
    # Phase 2
    "agent_resources",
    "service_process",
    # Phase 4
    "snmp",
    # Phase 5
    "proxmox_node",
    "proxmox_vm",
    "pbs_job",
    "opnsense",
    "unifi_device",
}

VALID_INTERVALS = {"1m", "5m", "15m", "30m", "1h", "6h", "12h", "24h"}

VALID_SEVERITIES = {"info", "warning", "critical"}
