# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pydantic import BaseModel, field_validator
from typing import Optional


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


# --- FRP Tunnel ---

class FrpTunnelCreate(BaseModel):
    server_id: str
    frp_config_id: str
    name: str  # proxy name, e.g. "k01-lnx1-ssh"
    tunnel_type: str  # "stcp" or "https"
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


class FrpTunnelUpdate(BaseModel):
    name: Optional[str] = None
    tunnel_type: Optional[str] = None
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
