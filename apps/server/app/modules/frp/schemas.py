# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.core.bounds import IntColumn, RequestModel
from app.core.config import FRP_BIND_PORT
from app.core.time import UtcDatetime
from app.modules.frp.extra_config import ALLOWED_KEYS, value_allowed

# These string fields are interpolated verbatim into the generated frps/frpc/
# visitor TOML (config_generator.py). Reject the characters that could break out
# of a TOML string and inject a directive (quote, backslash, newline, control
# chars — DEL included, TOML forbids it in a basic string) at the boundary, so
# the generator stays a pure interpolation. (Defense in depth — the fields are
# admin-set, so this is hardening, not an open hole.) TOML allows the C1 controls
# U+0080 to U+009F in a basic string, but the agent refuses every line of a
# frpc.toml with a unicode.IsControl character (U+0000 to U+001F, U+007F to
# U+009F), so they are rejected as well and the host is not left without a config.
_TOML_BREAKERS = set('"\\\n\r')


def _reject_toml_breakers(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    if any(c in _TOML_BREAKERS for c in v) or any(
        ord(c) < 0x20 or c == "\x7f" or 0x80 <= ord(c) <= 0x9F for c in v
    ):
        raise ValueError("enthält unzulässige Zeichen (Anführungszeichen/Backslash/Steuerzeichen)")
    # JSON can spell one as \ud800, and it has no UTF-8 form: no config file carries it.
    if any("\ud800" <= c <= "\udfff" for c in v):
        raise ValueError("must not contain a lone surrogate (U+D800 to U+DFFF)")
    # frp renders a config file as a Go template before it reads the TOML, so `{{`
    # would open a template action; a single brace and `}}` stay plain text.
    if "{{" in v:
        raise ValueError("must not contain '{{', which frp reads as the start of a template")
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
# A bare or dotted key of segments [A-Za-z0-9_-]+, as the agent takes them (serverKey in
# apps/agent/internal/frpc/servertoml.go); an empty segment (".a", "a.", "a..b") is no TOML key.
_TOML_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*")

# TOML integers are 64 bits; a Python int has no limit.
_TOML_INT_MIN, _TOML_INT_MAX = -(2**63), 2**63 - 1

# The keys the generator writes into each [[proxies]] table (generate_frpc_toml).
_GENERATOR_PROXY_KEYS = (
    "name",
    "type",
    "localIP",
    "localPort",
    "secretKey",
    "allowUsers",
    "customDomains",
)


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
                "(erlaubt: Segmente aus A-Z a-z 0-9 _ -, getrennt durch je einen .)"
            )
        if isinstance(value, str):
            _reject_toml_breakers(value)
        elif not isinstance(value, (bool, int, float)):
            raise ValueError(f"extra_config-Wert für '{key}' muss str, bool, int oder float sein")
        elif isinstance(value, int) and not isinstance(value, bool):
            if not _TOML_INT_MIN <= value <= _TOML_INT_MAX:
                raise ValueError(f"extra_config value for '{key}' is no 64-bit integer")
    return v


# frp maps the fields of a proxy without regard to case and reads its plugin from the
# member `plugin`, so `plugin`, `plugin.type` and `PLUGIN.type` all set up a proxy plugin.
# The server sets up none, and the agent refuses a frpc.toml with such a key in a proxy
# (apps/agent/internal/frpc/servertoml.go), so the whole host would get no config.
def is_plugin_key(key: str) -> bool:
    """Whether an extra_config key belongs to the plugin family: its first segment is
    `plugin` in any case. A key that passed _TOML_BARE_KEY is ASCII, so lower() is enough."""
    return key.split(".", 1)[0].lower() == "plugin"


def _take_key_path(root: dict, key: str) -> Optional[str]:
    """Enter key into the trie of a proxy's key paths; return the key it clashes with, if any."""
    node = root
    segments = key.lower().split(".")
    for segment in segments[:-1]:
        child = node.setdefault(segment, {})
        if isinstance(child, str):
            return child
        node = child
    last = segments[-1]
    if last not in node:
        node[last] = key
        return None
    taken = node[last]
    while isinstance(taken, dict):
        taken = next(iter(taken.values()))
    return taken


def _check_tunnel_extra_config(v: Optional[dict]) -> Optional[dict]:
    v = _check_extra_config(v)
    for key in v or {}:
        if is_plugin_key(key):
            raise ValueError(
                f"extra_config key '{key}' belongs to the plugin family; "
                "a tunnel sets up no proxy plugin"
            )
    # The agent refuses a proxy whose key paths repeat or nest, compared in lower case (frp
    # maps fields without regard to case): with the generator's keys and with each other.
    # Like keyTable.add, as a trie of the key paths by segment: a node is a key (its name) or
    # a table longer keys opened. Each key walks its segments once, so the check stays linear
    # in the size of the extra_config, however many or long its keys are.
    root: dict = {}
    for key in (*_GENERATOR_PROXY_KEYS, *(v or {})):
        clash = _take_key_path(root, key)
        if clash is not None:
            raise ValueError(
                f"extra_config key '{key}' clashes with '{clash}' (keys of a proxy are compared "
                "without regard to case, and none may be a prefix of another)"
            )
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

# bindPort, vhostHTTPSPort and webServer.port of the generated frps.toml (R-0411)
# and the bindPort of a visitor in the visitor TOML (visitor_port, R-0533; the
# desktop's allow-list refuses the whole visitor TOML for any other): a port, so
# narrower than the IntColumn of the column it lands in. The bounds sit inside
# Annotated so Optional[Port] keeps them on its integer branch. The generator
# guards server-config rows from before R-0411 with the same range.
PORT_MIN, PORT_MAX = 1, 65535
Port = Annotated[int, Field(ge=PORT_MIN, le=PORT_MAX)]
# maxPortsPerClient: frps enforces it only while it is > 0, so a negative value
# would lift the cap the generator always sets; 0 and null mean its default.
PortCount = Annotated[IntColumn, Field(ge=0)]


def dashboard_port_refused(dashboard_port: int, bind_port: Optional[int], published: int) -> bool:
    """Whether frps is not started with this webServer.port: check_config of
    apps/frps/frps-supervisor.sh refuses 443, the bindPort and FRP_BIND_PORT (published), the
    host port compose publishes for frps. A bind port of None matches nothing."""
    return dashboard_port in (443, bind_port, published)


def check_dashboard_port(dashboard_port: Optional[int], bind_port: Optional[int]) -> None:
    """dashboard_port_refused for the API (create schema, update route) with this server's
    FRP_BIND_PORT: a 422 before the frps supervisor refuses the config."""
    if dashboard_port is not None and dashboard_port_refused(
        dashboard_port, bind_port, FRP_BIND_PORT
    ):
        raise ValueError(
            "the dashboard port must be neither 443 nor the bind port nor FRP_BIND_PORT "
            f"({FRP_BIND_PORT})"
        )


def _check_create_dashboard_port(v: Optional[int], info: ValidationInfo) -> Optional[int]:
    # bind_port comes first, so info.data holds it as sent or as its default; it is
    # missing only when it failed its own check, which is a 422 already.
    check_dashboard_port(v, info.data.get("bind_port"))
    return v


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
    _v_dashboard_port = field_validator("dashboard_port")(_check_create_dashboard_port)


class FrpServerConfigUpdate(RequestModel):
    # The route checks the dashboard port (check_dashboard_port): it needs the bind port
    # the row has after the update.
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
    visitor_port: Optional[Port] = None  # STCP only
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
    _v_extra = field_validator("extra_config")(_check_tunnel_extra_config)


class FrpTunnelUpdate(RequestModel):
    name: Optional[str] = None
    tunnel_type: Optional[Literal["stcp", "https"]] = None
    protocol: Optional[str] = None
    local_ip: Optional[str] = None
    local_port: Optional[IntColumn] = None
    secret_key: Optional[str] = None
    custom_domains: Optional[str] = None
    visitor_port: Optional[Port] = None
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
    _v_extra = field_validator("extra_config")(_check_tunnel_extra_config)


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


class TunnelMappingOut(BaseModel):
    """A tunnel as a non-admin lists it: the keys of _MAPPING_FIELDS (tunnel_router.py)."""

    id: str
    serverId: str
    tunnelType: str
    protocol: str
    localPort: int
    visitorPort: Optional[int]
    customDomains: Optional[str]
    connectionId: Optional[str]
    enabled: Optional[bool]
    name: str


# The admin's full row first: a full row also passes TunnelMappingOut, which drops its other
# keys; a mapping row lacks the keys FrpTunnelOut requires and falls through to the second.
TunnelListItem = Annotated[FrpTunnelOut | TunnelMappingOut, Field(union_mode="left_to_right")]


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


class VisitorBundleOut(BaseModel):
    # pki stays {}: the server mints no PKI material any more, the key stays for the
    # desktop's response shape (gen_visitor_bundle).
    toml: str
    pki: dict[str, Any]


class ConfigHashOut(BaseModel):
    # null without an FRP config: nothing to sync (R-0398).
    hash: Optional[str]
