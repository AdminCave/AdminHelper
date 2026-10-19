# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.bounds import IntColumn, RequestModel
from app.core.time import UtcDatetime
from app.modules.frp.extra_config import ALLOWED_KEYS, value_allowed

# These string fields are interpolated verbatim into the generated frps/frpc/
# visitor TOML (config_generator.py). Reject the characters that could break out
# of a TOML string and inject a directive (quote, backslash, newline, control
# chars — DEL included, TOML forbids it in a basic string) at the boundary, so
# the generator stays a pure interpolation. (Defense in depth — the fields are
# admin-set, so this is hardening, not an open hole.)
_TOML_BREAKERS = set('"\\\n\r')


def _reject_toml_breakers(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    if any(c in _TOML_BREAKERS for c in v) or any(ord(c) < 0x20 or c == "\x7f" for c in v):
        raise ValueError("enthält unzulässige Zeichen (Anführungszeichen/Backslash/Steuerzeichen)")
    # JSON can spell one as \ud800, and it has no UTF-8 form: no config file carries it.
    if any("\ud800" <= c <= "\udfff" for c in v):
        raise ValueError("must not contain a lone surrogate (U+D800 to U+DFFF)")
    return v


def _check_secret(v: Optional[str]) -> Optional[str]:
    """secret_key / auth_token: if the client supplies one, require a minimum
    entropy floor (empty -> the server auto-generates a strong value)."""
    if v is None or v == "":
        return v
    v = _reject_toml_breakers(v)
    # Whitespace at either end adds nothing to guess; the value itself is kept as sent.
    if len(v.strip()) < 16:
        raise ValueError("must have at least 16 characters besides leading and trailing whitespace")
    return v


# The generator emits extra_config keys unquoted (`{key} = ...`), so they must
# be TOML bare keys (dotted keys allowed). Anything else would break — or worse,
# extend — the generated config.
_TOML_BARE_KEY = re.compile(r"[A-Za-z0-9_.-]+")


def _check_extra_config(v: Optional[dict]) -> Optional[dict]:
    """extra_config keys/values are emitted as TOML — same injection guard.

    Values are limited to scalars the generator can emit safely (str/bool/
    int/float): lists and dicts would land as raw Python repr in the TOML,
    which is neither valid TOML nor covered by the string guard (their inner
    strings bypass _reject_toml_breakers)."""
    if v is None:
        return v
    for key, value in v.items():
        if not _TOML_BARE_KEY.fullmatch(str(key)):
            raise ValueError(
                f"extra_config-Schlüssel '{key}' ist kein gültiger TOML-Key "
                "(erlaubt: A-Z a-z 0-9 _ . -)"
            )
        if isinstance(value, str):
            _reject_toml_breakers(value)
        elif not isinstance(value, (bool, int, float)):
            raise ValueError(f"extra_config-Wert für '{key}' muss str, bool, int oder float sein")
    return v


def _check_frps_extra_config(v: Optional[dict]) -> Optional[dict]:
    """The server config's extra_config goes into frps.toml, and the frps supervisor starts
    frps only with the keys and values of frp/extra_config.py (R-0411)."""
    v = _check_extra_config(v)
    for key, value in (v or {}).items():
        if key not in ALLOWED_KEYS:
            raise ValueError(
                f"extra_config key '{key}' is not allowed (allowed: "
                + ", ".join(sorted(ALLOWED_KEYS))
                + ")"
            )
        if not value_allowed(value):
            raise ValueError(
                f"extra_config value for '{key}' must be true, false, a finite number or a "
                "string without quotes, backslashes, braces or control characters"
            )
    return v


def _check_frps_string(v: Optional[str]) -> Optional[str]:
    """A string field the generator writes into frps.toml (STRING_FIELDS of
    frp/extra_config.py): on top of _reject_toml_breakers no brace, which the frps
    supervisor refuses anywhere in a line."""
    if v is not None and not value_allowed(v):
        raise ValueError("must not contain quotes, backslashes, braces or control characters")
    return v


def _validate_tags(tags: list[str] | None) -> list[str] | None:
    """Normalize a tag list: strip, cap at 50 chars, drop empties, deduplicate.

    Registered as field_validator(mode="before") in six places (frp, ansible,
    servers) so it sees the RAW value — the normalization has to run before
    Pydantic coerces. That also means the type check is this function's job: a
    dict, an int, None inside the list or a bool used to reach .strip() or the
    for loop and raise AttributeError/TypeError, which is not a ValidationError
    and left the route with an uncaught 500 instead of a 422. A bare string is
    rejected for the same reason it must not be accepted: iterating it would
    silently turn "ops" into three one-character tags.
    """
    if tags is None:
        return None
    if not isinstance(tags, list):
        raise ValueError("must be a list of strings")
    seen = set()
    result = []
    for t in tags:
        if not isinstance(t, str):
            raise ValueError("must be a list of strings")
        t = t.strip()[:50]
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return result


# --- FRP Server Config ---

# bindPort, vhostHTTPSPort and webServer.port of the generated frps.toml: a port,
# so narrower than the IntColumn of the column it lands in (R-0411). The bounds
# sit inside Annotated so Optional[Port] keeps them on its integer branch. The
# generator guards rows from before this bound with the same range.
PORT_MIN, PORT_MAX = 1, 65535
Port = Annotated[int, Field(ge=PORT_MIN, le=PORT_MAX)]
# maxPortsPerClient: frps enforces it only while it is > 0, so a negative value
# would lift the cap the generator always sets; 0 and null mean its default.
PortCount = Annotated[IntColumn, Field(ge=0)]


class FrpServerConfigCreate(RequestModel):
    name: str
    server_addr: str  # e.g. "frps.example.net"
    bind_port: Port = 7000
    vhost_https_port: Optional[Port] = None
    auth_token: Optional[str] = None  # auto-generated if empty
    subdomain_host: Optional[str] = None
    max_ports_per_client: Optional[PortCount] = None
    dashboard_port: Optional[Port] = None
    dashboard_user: Optional[str] = None
    dashboard_password: Optional[str] = None
    extra_config: Optional[dict] = None

    _v_str = field_validator("name", "server_addr", "subdomain_host", "dashboard_user")(
        _reject_toml_breakers
    )
    # dashboard_password guards a web UI exposing all proxy metadata + traffic, so
    # give it the same >=16-char entropy floor as auth_token (empty -> auto-generated
    # by the router when a dashboard port is set) (3.35).
    _v_token = field_validator("auth_token", "dashboard_password")(_check_secret)
    _v_extra = field_validator("extra_config")(_check_frps_extra_config)
    _v_frps = field_validator(
        "subdomain_host", "dashboard_user", "dashboard_password", "auth_token"
    )(_check_frps_string)


class FrpServerConfigUpdate(RequestModel):
    name: Optional[str] = None
    server_addr: Optional[str] = None
    # Not Optional: an explicit null is a 422, else the row stores NULL and frps
    # gets the generator's fallback. The None default only marks "not sent" —
    # pydantic does not validate defaults, and the router applies only the fields
    # that were sent.
    bind_port: Port = None
    vhost_https_port: Optional[Port] = None
    auth_token: Optional[str] = None
    subdomain_host: Optional[str] = None
    max_ports_per_client: Optional[PortCount] = None
    dashboard_port: Optional[Port] = None
    dashboard_user: Optional[str] = None
    dashboard_password: Optional[str] = None
    extra_config: Optional[dict] = None

    _v_str = field_validator("name", "server_addr", "subdomain_host", "dashboard_user")(
        _reject_toml_breakers
    )
    # dashboard_password guards a web UI exposing all proxy metadata + traffic, so
    # give it the same >=16-char entropy floor as auth_token (empty -> auto-generated
    # by the router when a dashboard port is set) (3.35).
    _v_token = field_validator("auth_token", "dashboard_password")(_check_secret)
    _v_extra = field_validator("extra_config")(_check_frps_extra_config)
    _v_frps = field_validator(
        "subdomain_host", "dashboard_user", "dashboard_password", "auth_token"
    )(_check_frps_string)


# --- FRP Tunnel ---


class FrpTunnelCreate(RequestModel):
    server_id: str
    frp_config_id: str
    name: str  # proxy name, e.g. "k01-lnx1-ssh"
    tunnel_type: Literal["stcp", "https"]
    protocol: str  # "ssh", "rdp", "web"
    local_ip: str = "127.0.0.1"
    local_port: IntColumn
    secret_key: Optional[str] = None  # auto-generated for STCP if empty
    custom_domains: Optional[str] = None  # HTTPS only
    visitor_port: Optional[IntColumn] = None  # STCP only
    connection_id: Optional[str] = None
    enabled: bool = True
    extra_config: Optional[dict] = None
    tags: list[str] = []
    auto_create_connection: bool = False  # automatically create a matching connection
    auto_connection_username: Optional[str] = None  # username for the auto-created connection

    _clean_tags = field_validator("tags", mode="before")(_validate_tags)
    _v_str = field_validator("name", "custom_domains", "local_ip", "auto_connection_username")(
        _reject_toml_breakers
    )
    _v_secret = field_validator("secret_key")(_check_secret)
    _v_extra = field_validator("extra_config")(_check_extra_config)


class FrpTunnelUpdate(RequestModel):
    name: Optional[str] = None
    tunnel_type: Optional[Literal["stcp", "https"]] = None
    protocol: Optional[str] = None
    local_ip: Optional[str] = None
    local_port: Optional[IntColumn] = None
    secret_key: Optional[str] = None
    custom_domains: Optional[str] = None
    visitor_port: Optional[IntColumn] = None
    connection_id: Optional[str] = None
    enabled: Optional[bool] = None
    extra_config: Optional[dict] = None
    tags: Optional[list[str]] = None
    auto_create_connection: bool = False
    auto_connection_username: Optional[str] = None

    _clean_tags = field_validator("tags", mode="before")(_validate_tags)
    _v_str = field_validator("name", "custom_domains", "local_ip", "auto_connection_username")(
        _reject_toml_breakers
    )
    _v_secret = field_validator("secret_key")(_check_secret)
    _v_extra = field_validator("extra_config")(_check_extra_config)


# --- Responses ---
# Key for key what FrpServerConfig.to_dict / FrpTunnel.to_dict hand out (R-0043): Pydantic
# drops a key the model does not declare without a word. Nullable columns are Optional
# (authToken and dashboardPassword also because every response but the create masks them),
# and the timestamps stay the strings to_dict builds (iso_utc: UTC with Z, R-0064).


class FrpServerConfigOut(BaseModel):
    id: str
    name: str
    serverAddr: str
    bindPort: Optional[int]
    vhostHttpsPort: Optional[int]
    authToken: Optional[str]
    subdomainHost: Optional[str]
    maxPortsPerClient: Optional[int]
    dashboardPort: Optional[int]
    dashboardUser: Optional[str]
    dashboardPassword: Optional[str]
    extraConfig: Optional[dict[str, Any]]
    createdAt: Optional[str]
    updatedAt: Optional[str]


class FrpTunnelOut(BaseModel):
    id: str
    serverId: str
    frpConfigId: str
    name: str
    tunnelType: str
    protocol: str
    localIp: Optional[str]
    localPort: int
    secretKey: Optional[str]
    customDomains: Optional[str]
    visitorPort: Optional[int]
    connectionId: Optional[str]
    enabled: Optional[bool]
    extraConfig: Optional[dict[str, Any]]
    tags: list[str]
    createdAt: Optional[str]


class FrpServerConfigDetail(FrpServerConfigOut):
    tunnels: list[FrpTunnelOut]


class FrpStatusProxy(BaseModel):
    # frps (0.69.1, ProxyStatsInfo) sends these as int64/string, never null; the router
    # fills a missing one with 0 or "".
    name: str
    type: str
    status: str
    curConns: int
    clientVersion: str
    todayTrafficIn: int
    todayTrafficOut: int
    lastStartTime: str
    lastCloseTime: str
    # An open object on purpose: which tunnel keys the status view promises is a
    # decision of its own, not a by-product of typing this route.
    tunnel: Optional[dict[str, Any]]


class FrpStatus(BaseModel):
    proxies: list[FrpStatusProxy]
    total: int
    # Only on the answer for an unreachable dashboard; the route drops it when unset.
    error: Optional[str] = None


class FrpSupervisorStatus(BaseModel):
    # Codes, times and a flag only, as supervisor_status.py hands them out. reason and
    # since are null for "missing"/"unreadable", lastEvent/lastEventAt without an event.
    state: str
    reason: Optional[str]
    since: Optional[UtcDatetime]
    stale: bool
    lastEvent: Optional[str]
    lastEventAt: Optional[UtcDatetime]
    publishedBindPort: int
