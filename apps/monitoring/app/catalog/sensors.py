# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensors the agent has compiled in, and what each one may be asked.

The server sends parameters, never commands (monitoring concept §3.8): a sensor is
a fixed measurement in the agent, and these models are the whole of what a catalog
entry or a probe check may set for it. The agent checks the same bounds again and
answers ``invalid`` to anything else, so a bound here is a promise, not the guard.

Each sensor returns a fixed set of fields (SENSOR_FIELDS, for opnsense, app and host the set
of its view); a view of the app sensor also fixes the kinds of its target (APP_VIEW_TARGETS). The sensors that read a structured answer (a JSON body, Redis INFO, HAProxy
stats) also return fields under ``data.`` — a path into that answer, which the agent
resolves to one scalar.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

SENSORS = (
    "unit",
    "process",
    "socket",
    "container",
    "http",
    "tls",
    "certfile",
    "file_age",
    "proto",
    "unixsocket",
    "sql",
    "dns",
    "log",
    "opnsense",
    "app",
    "host",
)

# The views of the opnsense sensor and the fields each one returns: the allowlist of the
# agent's internal/opnsense, read-only configd actions of the firewall (R-1248).
OPNSENSE_VIEW_FIELDS: dict[str, frozenset[str]] = {
    "services": frozenset({"total", "running", "stopped", "stopped_names"}),
    "gateways": frozenset(
        {
            "total",
            "down",
            "degraded",
            "forced_down",
            "down_names",
            "degraded_names",
            "max_loss_pct",
            "max_delay_ms",
        }
    ),
    "firmware": frozenset(
        {
            "version",
            "latest",
            "checked",
            "connection",
            "repository",
            "updates",
            "update_available",
            "update_reboot",
            "major_upgrade",
            "check_age_s",
        }
    ),
    "states": frozenset({"current", "limit", "used_pct"}),
    "carp": frozenset({"vips", "master", "backup", "init", "demotion", "maintenance"}),
}

# The views of the app sensor, the fields each one returns and the kinds of target it is bound
# to: the allowlist of the agent's sensor_app.go, each a fixed read of one application on its
# own host (R-1404). Counts, ages and a version; no name, password or content of the
# application ever leaves the agent.
APP_VIEW_FIELDS: dict[str, frozenset[str]] = {
    "bbb_meetings": frozenset(
        {"meetings", "running", "participants", "listeners", "voice", "video", "recording"}
    ),
    "bbb_recordings": frozenset(
        {
            "failed",
            "archive_failed",
            "sanity_failed",
            "process_failed",
            "publish_failed",
            "newest_fail_age_s",
        }
    ),
    "ldap_replication": frozenset(
        {"contexts", "csn_age_s", "monitor", "consumers", "disconnected", "refreshing"}
    ),
    "wordpress_version": frozenset({"version"}),
    "wg_peers": frozenset(
        {
            "interfaces",
            "peers",
            "keepalive_peers",
            "stale_warn",
            "stale_crit",
            "max_handshake_age_s",
        }
    ),
    "fail2ban": frozenset(
        {"responding", "jails", "banned_total", "max_banned", "jails_without_files"}
    ),
    "crowdsec_bouncers": frozenset({"bouncers", "stale_bouncers", "max_pull_age_s"}),
    "tailscale_status": frozenset({"backend_running", "health_warnings", "key_expiry_days"}),
    "openvpn_status": frozenset({"clients", "updated_age_s"}),
    "keepalived_vips": frozenset({"vips", "held"}),
    "bind_status": frozenset({"running", "zones", "recursive_clients", "recursive_limit"}),
    "unbound_stats": frozenset({"queries", "requestlist_exceeded", "servfail_pct"}),
    "chrony_tracking": frozenset({"synced", "stratum", "offset_abs_ms"}),
    "ntpsec_status": frozenset({"synced", "stratum", "offset_abs_ms"}),
    "nut_ups": frozenset(
        {
            "ups",
            "on_battery",
            "low_battery",
            "fsd",
            "overload",
            "replace_battery",
            "stale",
            "min_runtime_s",
            "min_charge_pct",
        }
    ),
    "apcupsd": frozenset(
        {"online", "on_battery", "low_battery", "commlost", "charge_pct", "runtime_s", "transfers"}
    ),
    "kea_pools": frozenset({"subnets", "max_pool_used_pct", "alloc_fail"}),
    "dnsmasq_leases": frozenset({"leases", "range_size", "used_pct"}),
    "caddy_upstreams": frozenset({"upstreams", "failing"}),
    "caddy_certs": frozenset({"certs", "expired", "min_days_left"}),
    "traefik_certs": frozenset({"certs", "expired", "min_days_left"}),
    "npm_certs": frozenset({"certs", "expired", "min_days_left"}),
}

# The views of the host sensor and the fields each one returns: the allowlist of the agent's
# sensor_host.go, parts of the agent's own host that belong to no unit and no container
# (R-1228). Counts and percentages only; no array, volume, controller or sensor name.
HOST_VIEW_FIELDS: dict[str, frozenset[str]] = {
    "mdadm": frozenset({"arrays", "degraded", "faulty_devices", "resyncing", "mismatch_cnt"}),
    "lvm_thin": frozenset({"pools", "max_data_pct", "max_meta_pct", "failed", "busy"}),
    "raid_ctrl": frozenset({"controllers", "ctrl_bad", "vd_not_optimal", "pd_failed", "bbu_bad"}),
    "ipmi_sensors": frozenset({"sensors", "critical", "noncritical"}),
}

_UNIT = frozenset({"unit"})
_CONTAINER = frozenset({"container"})
_UNIT_OR_CONTAINER = _UNIT | _CONTAINER
APP_VIEW_TARGETS: dict[str, frozenset[str]] = {
    "bbb_meetings": _UNIT,
    "bbb_recordings": _UNIT,
    "ldap_replication": _UNIT,
    "wordpress_version": _CONTAINER,
    "wg_peers": _UNIT,
    "fail2ban": _UNIT,
    "crowdsec_bouncers": _UNIT,
    "tailscale_status": _UNIT,
    "openvpn_status": _UNIT,
    "keepalived_vips": _UNIT,
    "bind_status": _UNIT,
    "unbound_stats": _UNIT,
    "chrony_tracking": _UNIT,
    "ntpsec_status": _UNIT,
    "nut_ups": _UNIT,
    "apcupsd": _UNIT,
    "kea_pools": _UNIT,
    "dnsmasq_leases": _UNIT,
    "caddy_upstreams": _UNIT,
    "caddy_certs": _UNIT_OR_CONTAINER,
    "traefik_certs": _UNIT_OR_CONTAINER,
    "npm_certs": _CONTAINER,
}

SENSOR_FIELDS: dict[str, frozenset[str]] = {
    "unit": frozenset({"active_state", "sub_state", "restarts", "active_since"}),
    "process": frozenset({"count", "rss_bytes", "uptime_s"}),
    "socket": frozenset({"listening", "port"}),
    "container": frozenset({"state", "health", "restarts", "started_at"}),
    "http": frozenset({"status_code", "duration_ms"}),
    "tls": frozenset({"days_left", "not_after", "hostname_ok", "chain_ok", "issuer"}),
    "certfile": frozenset({"days_left", "not_after", "issuer", "subject"}),
    "file_age": frozenset({"exists", "age_s", "size_bytes"}),
    "proto": frozenset({"ok", "duration_ms", "tls_ok", "detail"}),
    "unixsocket": frozenset({"connected", "duration_ms", "status_code"}),
    "sql": frozenset(
        {
            "ok",
            "duration_ms",
            "connections",
            "max_connections",
            "replication_running",
            "replication_lag_s",
            "size_bytes",
        }
    ),
    "dns": frozenset({"resolved", "duration_ms", "answers"}),
    "log": frozenset({"count"}),
    "opnsense": frozenset().union(*OPNSENSE_VIEW_FIELDS.values()),
    "app": frozenset().union(*APP_VIEW_FIELDS.values()),
    "host": frozenset().union(*HOST_VIEW_FIELDS.values()),
}

# Sensors whose answer is structured; they accept fields "data.<path>".
DATA_SENSORS = frozenset({"http", "proto", "unixsocket"})

# The targets a sensor may point at. None: the sensor names its object in params
# (a path, a query, a resolver lookup), it has no network or process target.
SENSOR_TARGETS: dict[str, frozenset[str] | None] = {
    "unit": frozenset({"unit"}),
    "process": frozenset({"process"}),
    "socket": frozenset({"port", "process", "container", "unit"}),
    "container": frozenset({"container"}),
    "http": frozenset({"loopback", "port", "process", "container", "unit"}),
    "tls": frozenset({"loopback", "port", "process", "container", "unit"}),
    "proto": frozenset({"loopback", "port", "process", "container", "unit"}),
    "certfile": None,
    "file_age": None,
    "unixsocket": None,
    "sql": None,
    "dns": None,
    "log": None,
    "opnsense": None,
    # Narrowed to the kinds of its view (APP_VIEW_TARGETS, checked on Check).
    "app": frozenset().union(*APP_VIEW_TARGETS.values()),
    "host": None,
}

FIELD_PATTERN = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_\-\[\]/]+)*$")
_ABS_PATH = r"^/[^\x00]*$"
_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME = rf"^{_LABEL}(\.{_LABEL})*\.?$"


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class NoParams(_Params):
    pass


class HttpParams(_Params):
    path: str = Field("/", pattern=r"^/[^\s\x00]*$", max_length=512)
    method: Literal["GET", "HEAD"] = "GET"
    # Host header localhost for apps that answer only to the names they trust (Nextcloud);
    # unset, the agent sends IP:port. No other name: a check must not pose as a site.
    host: Literal["localhost"] | None = None

    @field_validator("host", mode="before")
    @classmethod
    def _host_set_or_absent(cls, v: object) -> object:
        # A probe check sends its params as given, and the agent answers invalid to a null.
        if v is None:
            raise ValueError("host is localhost or left out")
        return v


class TlsParams(_Params):
    # The name the certificate must carry; empty: the name of the target.
    server_name: str = Field("", max_length=253)
    starttls: Literal["none", "smtp", "imap", "pop3", "ldap", "postgres"] = "none"


class PathParams(_Params):
    path: str = Field(pattern=_ABS_PATH, max_length=1024)


class ProtoParams(_Params):
    # auto: the agent recognises the protocol as its discovery does (banner, typical
    # probe, TLS) and reports it in `detail`; for a port no module knows.
    protocol: Literal[
        "auto", "banner", "smtp", "imap", "pop3", "ldap", "postgres", "redis", "fastcgi", "haproxy"
    ]
    starttls: StrictBool = False
    # fastcgi only: the status path of the pool (php-fpm pm.status_path).
    status_path: str = Field("", pattern=r"^(/[^\s\x00]*)?$", max_length=256)


class UnixSocketParams(_Params):
    path: str = Field(pattern=_ABS_PATH, max_length=1024)
    protocol: Literal["connect", "http", "redis", "fastcgi", "haproxy"] = "connect"
    http_path: str = Field("/", pattern=r"^/[^\s\x00]*$", max_length=512)
    status_path: str = Field("", pattern=r"^(/[^\s\x00]*)?$", max_length=256)


class SqlParams(_Params):
    engine: Literal["mariadb", "postgres"]
    # Fixed queries compiled into the agent; the server picks one, never writes SQL.
    query: Literal["ping", "connections", "replication", "size"]


class DnsParams(_Params):
    name: str = Field(pattern=_HOSTNAME, max_length=253)
    rrtype: Literal["A", "AAAA", "MX", "TXT", "SRV", "CNAME", "NS", "PTR"] = "A"


class LogParams(_Params):
    # The agent's own rules (sensor_log.go journalUnitPattern, logMatchPattern): what it
    # would answer with "invalid" is turned away here; empty means all units, no match.
    # The backslash is part of systemd's escaping (dev-disk-by\x2duuid-….service).
    unit: str = Field("", pattern=r"^([A-Za-z0-9:_.@\\\-]{1,255})?$")
    # journald priority: 0 emerg … 7 debug; counts entries at this level or worse.
    priority: int = Field(3, ge=0, le=7, strict=True)
    match: str = Field(
        "", pattern=r"^((SYSLOG_IDENTIFIER|_COMM|CONTAINER_NAME)=[A-Za-z0-9._@/:+\-]{1,100})?$"
    )


class OpnsenseParams(_Params):
    view: Literal["services", "gateways", "firmware", "states", "carp"]


class AppParams(_Params):
    view: Literal[
        "bbb_meetings",
        "bbb_recordings",
        "ldap_replication",
        "wordpress_version",
        "wg_peers",
        "fail2ban",
        "crowdsec_bouncers",
        "tailscale_status",
        "openvpn_status",
        "keepalived_vips",
        "bind_status",
        "unbound_stats",
        "chrony_tracking",
        "ntpsec_status",
        "nut_ups",
        "apcupsd",
        "kea_pools",
        "dnsmasq_leases",
        "caddy_upstreams",
        "caddy_certs",
        "traefik_certs",
        "npm_certs",
    ]


class HostParams(_Params):
    view: Literal["mdadm", "lvm_thin", "raid_ctrl", "ipmi_sensors"]


PARAM_MODELS: dict[str, type[_Params]] = {
    "unit": NoParams,
    "process": NoParams,
    "socket": NoParams,
    "container": NoParams,
    "http": HttpParams,
    "tls": TlsParams,
    "certfile": PathParams,
    "file_age": PathParams,
    "proto": ProtoParams,
    "unixsocket": UnixSocketParams,
    "sql": SqlParams,
    "dns": DnsParams,
    "log": LogParams,
    "opnsense": OpnsenseParams,
    "app": AppParams,
    "host": HostParams,
}


def field_allowed(sensor: str, field: str, params: dict) -> bool:
    """Whether `sensor` with `params` can return `field`: one of its own, or a data path."""
    if not FIELD_PATTERN.fullmatch(field):
        return False
    if sensor == "opnsense":
        return field in OPNSENSE_VIEW_FIELDS[params["view"]]
    if sensor == "app":
        return field in APP_VIEW_FIELDS[params["view"]]
    if sensor == "host":
        return field in HOST_VIEW_FIELDS[params["view"]]
    if field in SENSOR_FIELDS[sensor]:
        return True
    return sensor in DATA_SENSORS and field.startswith("data.") and len(field) > len("data.")


def validate_params(sensor: str, params: dict) -> dict:
    """The params of `sensor`, checked and with defaults filled in."""
    # An unset param (None) is not sent: an agent that predates it refuses the whole probe,
    # and the catalog version of a module that does not use it stays the same.
    return PARAM_MODELS[sensor].model_validate(params).model_dump(exclude_none=True)
