# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generates FRP configuration files (TOML) from the DB models."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.frp.models import FrpServerConfig, FrpTunnel


def _tls_server_block(
    server_name: str = "frps",
    pki_base_path: str = "/etc/frp/pki",
) -> list[str]:
    """Generates the [transport.tls] block for frps."""
    return [
        '', '[transport.tls]', 'force = true',
        f'certFile = "{pki_base_path}/{server_name}.crt"',
        f'keyFile = "{pki_base_path}/{server_name}.key"',
        f'trustedCaFile = "{pki_base_path}/ca.crt"',
    ]


def _tls_client_block(
    frpc_user: str = "",
    pki_base_path: str = "/etc/frp/pki",
) -> list[str]:
    """Generates the [transport.tls] block for frpc/visitor."""
    lines = ['', '[transport.tls]', 'enable = true']
    lines.append(f'trustedCaFile = "{pki_base_path}/ca.crt"')
    if frpc_user:
        lines.append(f'certFile = "{pki_base_path}/{frpc_user}.crt"')
        lines.append(f'keyFile = "{pki_base_path}/{frpc_user}.key"')
    return lines


def generate_frps_toml(config: FrpServerConfig) -> str:
    """Generates a complete frps.toml from the DB configuration."""
    lines = [
        f'bindPort = {config.bind_port}',
    ]

    if config.vhost_https_port:
        lines.append(f'vhostHTTPSPort = {config.vhost_https_port}')

    if config.subdomain_host:
        lines.append(f'subDomainHost = "{config.subdomain_host}"')

    if config.max_ports_per_client:
        lines.append(f'maxPortsPerClient = {config.max_ports_per_client}')

    lines.append('detailedErrorsToClient = false')
    lines.append('')

    # Dashboard
    if config.dashboard_port:
        lines.append(f'webServer.addr = "127.0.0.1"')
        lines.append(f'webServer.port = {config.dashboard_port}')
        if config.dashboard_user:
            lines.append(f'webServer.user = "{config.dashboard_user}"')
        if config.dashboard_password:
            lines.append(f'webServer.password = "{config.dashboard_password}"')
        lines.append('')

    # Auth
    lines.append('auth.method = "token"')
    lines.append(f'auth.token = "{config.auth_token}"')

    lines.extend(_tls_server_block())

    return '\n'.join(lines) + '\n'


def generate_frpc_toml(
    config: FrpServerConfig,
    tunnels: list[FrpTunnel],
    frpc_user: str,
    allow_users: list[str] | None = None,
) -> str:
    """Generates a frpc.toml for a target host.

    Args:
        config: The central frps configuration.
        tunnels: All tunnels belonging to this host.
        frpc_user: The frpc user identifier (e.g. "k01-lnx1").
    """
    import json as _json

    lines = [
        f'serverAddr = "{config.server_addr}"',
        f'serverPort = {config.bind_port}',
        f'user = "{frpc_user}"',
        '',
        'auth.method = "token"',
        f'auth.token = "{config.auth_token}"',
    ]

    lines.extend(_tls_client_block(frpc_user))

    active_tunnels = [t for t in tunnels if t.enabled]

    for tunnel in active_tunnels:
        lines.append('')
        lines.append('[[proxies]]')
        lines.append(f'name = "{tunnel.name}"')
        lines.append(f'type = "{tunnel.tunnel_type}"')
        lines.append(f'localIP = "{tunnel.local_ip}"')
        lines.append(f'localPort = {tunnel.local_port}')

        if tunnel.tunnel_type == "stcp":
            lines.append(f'secretKey = "{tunnel.secret_key}"')
            users = allow_users if allow_users else ["ops-admin"]
            user_list = ", ".join(f'"{u}"' for u in users)
            lines.append(f'allowUsers = [{user_list}]')

        if tunnel.tunnel_type == "https" and tunnel.custom_domains:
            domains = [d.strip() for d in tunnel.custom_domains.split(",")]
            domain_list = ", ".join(f'"{d}"' for d in domains)
            lines.append(f'customDomains = [{domain_list}]')

        if tunnel.extra_config:
            extra = _json.loads(tunnel.extra_config) if isinstance(tunnel.extra_config, str) else tunnel.extra_config
            for key, value in extra.items():
                if isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                elif isinstance(value, bool):
                    lines.append(f'{key} = {"true" if value else "false"}')
                else:
                    lines.append(f'{key} = {value}')

    return '\n'.join(lines) + '\n'


def generate_visitor_toml(
    config: FrpServerConfig,
    tunnels: list[FrpTunnel],
    visitor_user: str = "ops-admin",
    pki_base_path: str = "/etc/frp/pki",
) -> str:
    """Generates a visitor frpc.toml for the admin PC.

    Aggregates all STCP tunnels and emits one [[visitors]] block each.
    """
    lines = [
        f'serverAddr = "{config.server_addr}"',
        f'serverPort = {config.bind_port}',
        f'user = "{visitor_user}"',
        '',
        'auth.method = "token"',
        f'auth.token = "{config.auth_token}"',
    ]

    lines.extend(_tls_client_block(visitor_user, pki_base_path))

    stcp_tunnels = [t for t in tunnels if t.tunnel_type == "stcp" and t.enabled]
    stcp_tunnels.sort(key=lambda t: t.visitor_port or 0)

    for tunnel in stcp_tunnels:
        # FRP registers proxies as "{agent_user}.{proxy_name}".
        # The visitor must set serverUser to the agent user so that
        # FRP finds the proxy as "{serverUser}.{serverName}".
        agent_user = tunnel.target_server.name if tunnel.target_server else ""

        lines.append('')
        lines.append('[[visitors]]')
        lines.append(f'name = "{tunnel.name}-visitor"')
        lines.append(f'type = "stcp"')
        lines.append(f'serverName = "{tunnel.name}"')
        if agent_user:
            lines.append(f'serverUser = "{agent_user}"')
        lines.append(f'secretKey = "{tunnel.secret_key}"')
        lines.append(f'bindAddr = "127.0.0.1"')
        lines.append(f'bindPort = {tunnel.visitor_port}')

    return '\n'.join(lines) + '\n'
