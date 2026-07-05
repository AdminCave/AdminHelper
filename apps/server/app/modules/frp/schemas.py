# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

# These string fields are interpolated verbatim into the generated frps/frpc/
# visitor TOML (config_generator.py). Reject the characters that could break out
# of a TOML string and inject a directive (quote, backslash, newline, control
# chars) at the boundary, so the generator stays a pure interpolation. (Defense
# in depth — the fields are admin-set, so this is hardening, not an open hole.)
_TOML_BREAKERS = set('"\\\n\r')


def _reject_toml_breakers(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    if any(c in _TOML_BREAKERS for c in v) or any(ord(c) < 0x20 for c in v):
        raise ValueError("enthält unzulässige Zeichen (Anführungszeichen/Backslash/Steuerzeichen)")
    return v


def _check_secret(v: Optional[str]) -> Optional[str]:
    """secret_key / auth_token: if the client supplies one, require a minimum
    entropy floor (empty -> the server auto-generates a strong value)."""
    if v is None or v == "":
        return v
    v = _reject_toml_breakers(v)
    if len(v) < 16:
        raise ValueError("muss mindestens 16 Zeichen lang sein")
    return v


# The generator emits extra_config keys unquoted (`{key} = ...`), so they must
# be TOML bare keys (dotted keys allowed). Anything else would break — or worse,
# extend — the generated config.
_TOML_BARE_KEY = re.compile(r"^[A-Za-z0-9_.-]+$")


def _check_extra_config(v: Optional[dict]) -> Optional[dict]:
    """extra_config keys/values are emitted as TOML — same injection guard.

    Values are limited to scalars the generator can emit safely (str/bool/
    int/float): lists and dicts would land as raw Python repr in the TOML,
    which is neither valid TOML nor covered by the string guard (their inner
    strings bypass _reject_toml_breakers)."""
    if v is None:
        return v
    for key, value in v.items():
        if not _TOML_BARE_KEY.match(str(key)):
            raise ValueError(
                f"extra_config-Schlüssel '{key}' ist kein gültiger TOML-Key "
                "(erlaubt: A-Z a-z 0-9 _ . -)"
            )
        if isinstance(value, str):
            _reject_toml_breakers(value)
        elif not isinstance(value, (bool, int, float)):
            raise ValueError(f"extra_config-Wert für '{key}' muss str, bool, int oder float sein")
    return v


def _validate_tags(tags: list[str] | None) -> list[str] | None:
    if tags is None:
        return None
    seen = set()
    result = []
    for t in tags:
        t = t.strip()[:50]
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return result


# --- FRP Server Config ---


class FrpServerConfigCreate(BaseModel):
    name: str
    server_addr: str  # e.g. "frps.example.net"
    bind_port: int = 7000
    vhost_https_port: Optional[int] = None
    auth_token: Optional[str] = None  # auto-generated if empty
    subdomain_host: Optional[str] = None
    max_ports_per_client: Optional[int] = None
    dashboard_port: Optional[int] = None
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
    _v_extra = field_validator("extra_config")(_check_extra_config)


class FrpServerConfigUpdate(BaseModel):
    name: Optional[str] = None
    server_addr: Optional[str] = None
    bind_port: Optional[int] = None
    vhost_https_port: Optional[int] = None
    auth_token: Optional[str] = None
    subdomain_host: Optional[str] = None
    max_ports_per_client: Optional[int] = None
    dashboard_port: Optional[int] = None
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
    _v_extra = field_validator("extra_config")(_check_extra_config)


# --- FRP Tunnel ---


class FrpTunnelCreate(BaseModel):
    server_id: str
    frp_config_id: str
    name: str  # proxy name, e.g. "k01-lnx1-ssh"
    tunnel_type: Literal["stcp", "https"]
    protocol: str  # "ssh", "rdp", "web"
    local_ip: str = "127.0.0.1"
    local_port: int
    secret_key: Optional[str] = None  # auto-generated for STCP if empty
    custom_domains: Optional[str] = None  # HTTPS only
    visitor_port: Optional[int] = None  # STCP only
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


class FrpTunnelUpdate(BaseModel):
    name: Optional[str] = None
    tunnel_type: Optional[Literal["stcp", "https"]] = None
    protocol: Optional[str] = None
    local_ip: Optional[str] = None
    local_port: Optional[int] = None
    secret_key: Optional[str] = None
    custom_domains: Optional[str] = None
    visitor_port: Optional[int] = None
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
