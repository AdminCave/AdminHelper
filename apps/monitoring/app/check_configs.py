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
defaults but are NOT materialized into storage (validation only).

Number fields are strict (R-0487): the config is stored as sent, so a lax
field let "85" or true through to the checker, which failed on the string and
read true as 1."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

from app.catalog.model import INTERVALS, Check, Rule
from app.core.bounds import CREDENTIAL_REF_MAX, CREDENTIAL_REF_PATTERN


class _StrictConfig(BaseModel):
    # Finite only: the config is stored as sent, and json.dumps writes inf back as
    # the token Infinity, which is no JSON number (RFC 8259 section 6).
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PingConfig(_StrictConfig):
    target: str = Field(min_length=1)
    timeout: float = Field(5, ge=1, le=300, strict=True)


class TcpConfig(_StrictConfig):
    target: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535, strict=True)
    timeout: float = Field(5, ge=1, le=300, strict=True)


class HttpConfig(_StrictConfig):
    url: str = Field(min_length=1)
    method: str = Field("GET", min_length=1)
    expected_status: int = Field(200, ge=100, le=599, strict=True)
    timeout: float = Field(10, ge=1, le=300, strict=True)
    verify_ssl: StrictBool = True
    search_string: str = ""


class AgentPingConfig(_StrictConfig):
    # server_id stays optional: template defs inject it via {{server_id}}, but a
    # hand-created check without it degrades to 'unknown' (visible, not alerting).
    server_id: str = ""
    stale_minutes: float = Field(15, ge=1, le=1440, strict=True)


class _TempOverride(_StrictConfig):
    warn: float | None = Field(None, ge=0, le=200, strict=True)
    crit: float | None = Field(None, ge=0, le=200, strict=True)


class _DiskOverride(_StrictConfig):
    warn: float | None = Field(None, ge=0, le=100, strict=True)
    crit: float | None = Field(None, ge=0, le=100, strict=True)
    min_free_gb: float | None = Field(None, ge=0, le=1_000_000, strict=True)


class AgentResourcesConfig(_StrictConfig):
    cpu_warn: float = Field(80, ge=0, le=100, strict=True)
    cpu_crit: float = Field(95, ge=0, le=100, strict=True)
    memory_warn: float = Field(80, ge=0, le=100, strict=True)
    memory_crit: float = Field(95, ge=0, le=100, strict=True)
    disk_warn: float = Field(85, ge=0, le=100, strict=True)
    disk_crit: float = Field(95, ge=0, le=100, strict=True)
    # A disk's percentage alarm counts only below this many GB free (free_gb, agent v3);
    # 0 turns the gate off. ignore_mounts and disk_overrides name exact mount paths.
    disk_min_free_gb: float = Field(20, ge=0, le=1_000_000, strict=True)
    ignore_mounts: list[str] = []
    disk_overrides: dict[str, _DiskOverride] = {}
    swap_warn: float = Field(80, ge=0, le=100, strict=True)
    swap_crit: float = Field(95, ge=0, le=100, strict=True)
    inode_warn: float = Field(80, ge=0, le=100, strict=True)
    inode_crit: float = Field(90, ge=0, le=100, strict=True)
    # Per CPU: load_5m / cpu_count, not a percentage.
    load_warn: float = Field(1.5, ge=0, le=100, strict=True)
    load_crit: float = Field(3.0, ge=0, le=100, strict=True)
    temp_warn: float = Field(80, ge=0, le=200, strict=True)
    temp_crit: float = Field(95, ge=0, le=200, strict=True)
    temp_overrides: dict[str, _TempOverride] = {}
    # Entry/release hysteresis in percentage points (T6): once a metric is
    # warning/critical, its thresholds drop by this much until it clears. Not for
    # the load, which is no percentage.
    hysteresis_pp: float = Field(10, ge=0, le=50, strict=True)


class ServiceProcessConfig(_StrictConfig):
    mode: Literal["auto", "list"] = "list"
    ignore: list[str] | str = []
    services: list[str] = []


class SmartHealthConfig(_StrictConfig):
    ignore_devices: list[str] = []
    reallocated_warn: float = Field(1, ge=0, strict=True)
    reallocated_crit: float = Field(10, ge=0, strict=True)
    pending_warn: float = Field(1, ge=0, strict=True)
    pending_crit: float = Field(5, ge=0, strict=True)
    nvme_spare_warn: float = Field(20, ge=0, le=100, strict=True)
    nvme_spare_crit: float = Field(10, ge=0, le=100, strict=True)
    nvme_used_warn: float = Field(90, ge=0, strict=True)
    nvme_used_crit: float = Field(100, ge=0, strict=True)
    temp_hdd_warn: float = Field(55, ge=0, le=200, strict=True)
    temp_hdd_crit: float = Field(60, ge=0, le=200, strict=True)
    temp_ssd_warn: float = Field(60, ge=0, le=200, strict=True)
    temp_ssd_crit: float = Field(70, ge=0, le=200, strict=True)
    temp_nvme_warn: float = Field(65, ge=0, le=200, strict=True)
    temp_nvme_crit: float = Field(75, ge=0, le=200, strict=True)


class ProxmoxBackupConfig(_StrictConfig):
    max_backup_age_hours: float = Field(26, ge=1, le=8760, strict=True)
    # A number is a Proxmox VE VMID: qm(1) gives 100 - 999999999.
    exclude_vmids: list[Annotated[int, Field(ge=100, le=999_999_999)] | str] = []
    exclude_stopped: StrictBool = True
    # Strict: configs are stored as sent, and a lax "false" or 0 would reach the
    # checker and the desktop checkbox as values each reads differently.
    alert_on_unavailable: StrictBool = True


class ZfsHealthConfig(_StrictConfig):
    capacity_warn: float = Field(80, ge=0, le=100, strict=True)
    capacity_crit: float = Field(90, ge=0, le=100, strict=True)
    # Strict: configs are stored as sent, and a lax "false" or 0 would reach the
    # checker and the desktop checkbox as values each reads differently.
    alert_on_unavailable: StrictBool = True


class DockerHealthConfig(_StrictConfig):
    ignore_containers: list[str] = []
    alert_on_unavailable: StrictBool = True
    # Dead key, deliberately tolerated: the checker never reads it, but the
    # desktop UI's docker_health form writes it on every toggle — rejecting it
    # would 422 product-generated configs. UI cleanup happens in T20.
    check_restarts: StrictBool = False


class DiskForecastConfig(_StrictConfig):
    # server_id via template placeholder {{server_id}}; empty degrades to
    # 'unknown' at runtime like agent_ping.
    server_id: str = ""
    window_hours: float = Field(24, ge=1, le=168, strict=True)
    min_history_hours: float = Field(6, ge=1, le=48, strict=True)
    warn_hours: float = Field(24, ge=1, le=8760, strict=True)
    crit_hours: float = Field(8, ge=1, le=8760, strict=True)


class SystemStateConfig(_StrictConfig):
    # Strict: configs are stored as sent, and the checker switches a point off only on
    # a real false; a lax "false" or 0 would be stored and keep the point on.
    check_reboot: StrictBool = True
    check_time_sync: StrictBool = True
    check_security_updates: StrictBool = True
    check_oom: StrictBool = True


class ProbeTarget(_StrictConfig):
    # kind and scheme are checked by the catalog's Target (ProbeConfig below).
    kind: str
    # The instance's own container, unit or process the agent asks; empty for a port.
    name: str = Field("", max_length=255, pattern=r"^[^\x00-\x1f\x7f]*$")
    port_hint: int | None = Field(None, ge=1, le=65535, strict=True)
    scheme: str | None = None


class ProbeCredential(_StrictConfig):
    ref: str = Field(max_length=CREDENTIAL_REF_MAX, pattern=CREDENTIAL_REF_PATTERN)
    use: str


class ProbeConfig(_StrictConfig):
    """A sensor of the agent run against one module instance (R-1223)."""

    sensor: str
    target: ProbeTarget | None = None
    params: dict[str, Any] = {}
    interval_s: int = Field(300, strict=True)
    timeout_s: int = Field(10, ge=1, le=30, strict=True)
    fields: list[str] = []
    rules: list[Rule] = []
    credential: ProbeCredential | None = None
    test_object: StrictBool = False

    @field_validator("interval_s")
    @classmethod
    def _allowed_interval(cls, v: int) -> int:
        if v not in INTERVALS:
            raise ValueError(f"interval_s must be one of {INTERVALS}")
        return v

    @model_validator(mode="after")
    def _fits_the_catalog(self) -> ProbeConfig:
        # A probe check is a catalog check bound to one instance: the catalog's rules
        # (sensor params, returned fields, targets, test objects) hold for it alike.
        target = self.target
        if (
            target is not None
            and target.kind in ("container", "unit", "process")
            and not target.name
        ):
            # The agent asks exactly this container, unit or process; without a name it
            # would have to guess.
            raise ValueError(f"target.name is required for kind '{target.kind}'")
        try:
            Check.model_validate(
                {
                    "key": "probe",
                    "name": "probe",
                    "sensor": self.sensor,
                    "target": None
                    if target is None
                    else {
                        "kind": target.kind,
                        "port_hint": target.port_hint,
                        "scheme": target.scheme,
                    },
                    "params": self.params,
                    "interval": self.interval_s,
                    "timeout_s": self.timeout_s,
                    "fields": self.fields,
                    "rules": self.rules,
                    "credential": None if self.credential is None else {"use": self.credential.use},
                    "test_object": self.test_object,
                }
            )
        except ValidationError as exc:
            raise ValueError(
                "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"]
                    for e in exc.errors()
                )
            ) from exc
        return self


class TlsParams(_StrictConfig):
    """The tls sensor takes no params; extra=forbid refuses any key."""


class DnsParams(_StrictConfig):
    """The addresses the name must resolve to; without them the first complete answer
    becomes the baseline."""

    expected: list[str] | None = Field(None, min_length=1, max_length=32)

    @field_validator("expected")
    @classmethod
    def _addresses(cls, v: list[str] | None) -> list[str] | None:
        for entry in v or []:
            try:
                ip = ipaddress.ip_address(entry)
            except ValueError:
                raise ValueError(f"{entry!r} is not an IP address") from None
            if ip.version == 6 and ip.scope_id:
                raise ValueError(f"{entry!r} carries a zone index")
        return v


class RdapParams(_StrictConfig):
    """Days before the registry's expiry date from which the sensor warns or is critical."""

    warn_days: int = Field(30, ge=1, le=365, strict=True)
    crit_days: int = Field(7, ge=0, le=364, strict=True)

    @model_validator(mode="after")
    def _crit_before_warn(self):
        if self.crit_days >= self.warn_days:
            raise ValueError("crit_days must be below warn_days")
        return self


class MailParams(_StrictConfig):
    """The mail sensors take no params; the port picks the protocol."""


class MailDnsParams(_StrictConfig):
    """The sensor mail_dns takes no params; extra=forbid refuses any key."""


@dataclass(frozen=True)
class CentralSensor:
    """One sensor of a central check (R-1224): its shortest and its default interval,
    the port a config without one uses (None: the sensor takes no port), the model of
    its params, whether the host must be a name, and the only ports it takes (None: any)."""

    min_interval: str
    default_interval: str
    default_port: int | None
    params: type[_StrictConfig]
    needs_name: bool = False
    ports: tuple[int, ...] | None = None


CENTRAL_SENSORS: dict[str, CentralSensor] = {
    "tls": CentralSensor("15m", "1h", 443, TlsParams),
    "dns": CentralSensor("5m", "15m", None, DnsParams, needs_name=True),
    "rdap": CentralSensor("24h", "24h", None, RdapParams, needs_name=True),
    # A mail server is contacted at most every 15 minutes per address and port
    # (postscreen, fail2ban): a shorter interval would only be skipped.
    "smtp": CentralSensor("15m", "15m", 25, MailParams, ports=(25, 465, 587)),
    "imap": CentralSensor("15m", "15m", 993, MailParams, ports=(143, 993, 995)),
    # Mail records change seldom; hourly also bounds the MTA-STS policy fetches.
    "mail_dns": CentralSensor("1h", "1h", None, MailDnsParams, needs_name=True),
}
# The agent sensors whose view of the same service explains a central result (T10).
CENTRAL_PAIR_SENSORS = frozenset({"tls", "certfile", "http"})
# SSH and MySQL are never probed from outside: a cyclic connection there reads as an
# attack to the target's fail2ban or fills its error log (concept §3.7).
CENTRAL_FORBIDDEN_PORTS = frozenset({22, 3306})

_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


class CentralConfig(_StrictConfig):
    """A probe the monitoring service runs itself against a public endpoint (R-1224)."""

    sensor: str
    host: str = Field(min_length=1, max_length=253)
    port: int | None = Field(None, ge=1, le=65535, strict=True)
    pair_check_id: str | None = Field(None, min_length=1, max_length=64)
    params: dict[str, Any] = {}

    @field_validator("sensor")
    @classmethod
    def _sensor_known(cls, v: str) -> str:
        if v not in CENTRAL_SENSORS:
            raise ValueError(f"unknown sensor; allowed: {', '.join(sorted(CENTRAL_SENSORS))}")
        return v

    @field_validator("host")
    @classmethod
    def _host_valid(cls, v: str) -> str:
        try:
            ip = ipaddress.ip_address(v)
        except ValueError:
            ip = None
        if ip is not None:
            # A zone index names an interface of this host, never a public endpoint.
            if ip.version == 6 and ip.scope_id:
                raise ValueError("an IPv6 address with a zone index is not public")
            return v
        labels = v.split(".")
        # ASCII host names only (an IDN in its xn-- form): the name goes to the public
        # resolvers and into the SNI as written. An all-digit last label is no TLD, so
        # 1.2.3 or 999.1.1.1 cannot pass as a name.
        if not all(_HOST_LABEL.fullmatch(label) for label in labels) or labels[-1].isdigit():
            raise ValueError("must be a host name (letters, digits, hyphens) or an IP address")
        return v

    @field_validator("port")
    @classmethod
    def _port_allowed(cls, v: int | None) -> int | None:
        if v in CENTRAL_FORBIDDEN_PORTS:
            raise ValueError("ports 22 and 3306 are never probed from outside")
        return v

    @model_validator(mode="after")
    def _fits_sensor(self):
        sensor = CENTRAL_SENSORS[self.sensor]
        if sensor.default_port is None and self.port is not None:
            raise ValueError(f"the sensor {self.sensor} takes no port")
        if sensor.ports is not None and self.port is not None and self.port not in sensor.ports:
            allowed = ", ".join(map(str, sensor.ports[:-1])) + f" or {sensor.ports[-1]}"
            raise ValueError(f"the sensor {self.sensor} takes port {allowed}")
        if sensor.needs_name and _is_ip(self.host):
            raise ValueError(f"the sensor {self.sensor} needs a host name, not an IP address")
        return self

    @model_validator(mode="after")
    def _params_valid(self):
        try:
            CENTRAL_SENSORS[self.sensor].params.model_validate(self.params)
        except ValidationError as exc:
            raise ValueError(
                "; ".join(
                    f"params.{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                    if e["loc"]
                    else f"params: {e['msg']}"
                    for e in exc.errors()
                )
            ) from exc
        return self


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
    "disk_forecast": DiskForecastConfig,
    "system_state": SystemStateConfig,
    "probe": ProbeConfig,
    "central": CentralConfig,
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
        raise ValueError(f"Invalid config for {check_type}: {details}") from exc
