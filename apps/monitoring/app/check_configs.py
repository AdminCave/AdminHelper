# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-check-type config schemas — validated at the API boundary.

A check's ``config`` used to be a free-form dict: a typo'd key (``cpu_wanr``)
or an out-of-range value silently fell back to the checker default and
surfaced only as a permanently-unknown or mis-thresholded check at runtime.
These models reject unknown keys and out-of-range values at create/update time
and for template definitions. Existing stored rows are never re-validated —
only payloads crossing the boundary. Defaults here mirror the checker
defaults but are NOT materialized into storage (validation only)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PingConfig(_StrictConfig):
    target: str = Field(min_length=1)
    timeout: float = Field(5, ge=1, le=300)


class TcpConfig(_StrictConfig):
    target: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    timeout: float = Field(5, ge=1, le=300)


class HttpConfig(_StrictConfig):
    url: str = Field(min_length=1)
    method: str = Field("GET", min_length=1)
    expected_status: int = Field(200, ge=100, le=599)
    timeout: float = Field(10, ge=1, le=300)
    verify_ssl: bool = True
    search_string: str = ""


class AgentPingConfig(_StrictConfig):
    # server_id stays optional: template defs inject it via {{server_id}}, but a
    # hand-created check without it degrades to 'unknown' (visible, not alerting).
    server_id: str = ""
    stale_minutes: float = Field(15, ge=1, le=1440)


class _TempOverride(_StrictConfig):
    warn: float | None = Field(None, ge=0, le=200)
    crit: float | None = Field(None, ge=0, le=200)


class AgentResourcesConfig(_StrictConfig):
    cpu_warn: float = Field(80, ge=0, le=100)
    cpu_crit: float = Field(95, ge=0, le=100)
    memory_warn: float = Field(80, ge=0, le=100)
    memory_crit: float = Field(95, ge=0, le=100)
    disk_warn: float = Field(85, ge=0, le=100)
    disk_crit: float = Field(95, ge=0, le=100)
    temp_warn: float = Field(80, ge=0, le=200)
    temp_crit: float = Field(95, ge=0, le=200)
    temp_overrides: dict[str, _TempOverride] = {}
    # Entry/release hysteresis in percentage points (T6): once a metric is
    # warning/critical, its thresholds drop by this much until it clears.
    hysteresis_pp: float = Field(10, ge=0, le=50)


class ServiceProcessConfig(_StrictConfig):
    mode: Literal["auto", "list"] = "list"
    ignore: list[str] | str = []
    services: list[str] = []


class SmartHealthConfig(_StrictConfig):
    ignore_devices: list[str] = []
    reallocated_warn: float = Field(1, ge=0)
    reallocated_crit: float = Field(10, ge=0)
    pending_warn: float = Field(1, ge=0)
    pending_crit: float = Field(5, ge=0)
    nvme_spare_warn: float = Field(20, ge=0, le=100)
    nvme_spare_crit: float = Field(10, ge=0, le=100)
    nvme_used_warn: float = Field(90, ge=0)
    nvme_used_crit: float = Field(100, ge=0)
    temp_hdd_warn: float = Field(55, ge=0, le=200)
    temp_hdd_crit: float = Field(60, ge=0, le=200)
    temp_ssd_warn: float = Field(60, ge=0, le=200)
    temp_ssd_crit: float = Field(70, ge=0, le=200)
    temp_nvme_warn: float = Field(65, ge=0, le=200)
    temp_nvme_crit: float = Field(75, ge=0, le=200)


class ProxmoxBackupConfig(_StrictConfig):
    max_backup_age_hours: float = Field(26, ge=1, le=8760)
    exclude_vmids: list[int | str] = []
    exclude_stopped: bool = True


class ZfsHealthConfig(_StrictConfig):
    capacity_warn: float = Field(80, ge=0, le=100)
    capacity_crit: float = Field(90, ge=0, le=100)


class DockerHealthConfig(_StrictConfig):
    ignore_containers: list[str] = []
    # Dead key, deliberately tolerated: the checker never reads it, but the
    # desktop UI's docker_health form writes it on every toggle — rejecting it
    # would 422 product-generated configs. UI cleanup happens in T20.
    check_restarts: bool = False


CONFIG_MODELS: dict[str, type[_StrictConfig]] = {
    "ping": PingConfig,
    "tcp": TcpConfig,
    "http": HttpConfig,
    "agent_ping": AgentPingConfig,
    "agent_resources": AgentResourcesConfig,
    "service_process": ServiceProcessConfig,
    "smart_health": SmartHealthConfig,
    "proxmox_backup": ProxmoxBackupConfig,
    "zfs_health": ZfsHealthConfig,
    "docker_health": DockerHealthConfig,
}


def validate_check_config(check_type: str, config: dict) -> None:
    """Raises ValueError when the config does not fit the type's schema.

    Unknown check types pass through — they are rejected separately against
    VALID_CHECK_TYPES; this function must not duplicate that gate."""
    model = CONFIG_MODELS.get(check_type)
    if model is None:
        return
    try:
        model.model_validate(config or {})
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'config'}: {e['msg']}" for e in exc.errors()
        )
        raise ValueError(f"Ungueltige Config fuer {check_type}: {details}") from exc
