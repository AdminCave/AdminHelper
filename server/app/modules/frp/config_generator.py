"""Generiert FRP-Konfigurationsdateien (TOML) aus den DB-Modellen."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.frp.models import FrpServerConfig, FrpTunnel


def _tls_server_block(config: FrpServerConfig) -> list[str]:
    """Generiert den [transport.tls]-Block fuer frps."""
    if not config.tls_force:
        return []
    lines = ['', '[transport.tls]', 'force = true']
    if config.tls_cert_file:
        lines.append(f'certFile = "{config.tls_cert_file}"')
    if config.tls_key_file:
        lines.append(f'keyFile = "{config.tls_key_file}"')
    if config.tls_ca_file:
        lines.append(f'trustedCaFile = "{config.tls_ca_file}"')
    return lines


def _tls_client_block(config: FrpServerConfig, frpc_user: str = "") -> list[str]:
    """Generiert den [transport.tls]-Block fuer frpc/visitor."""
    if not config.tls_force:
        return []
    lines = ['', '[transport.tls]', 'enable = true']
    if config.tls_ca_file:
        lines.append(f'trustedCaFile = "/etc/frp/pki/ca.crt"')
    if frpc_user:
        lines.append(f'certFile = "/etc/frp/pki/{frpc_user}.crt"')
        lines.append(f'keyFile = "/etc/frp/pki/{frpc_user}.key"')
    return lines


def generate_frps_toml(config: FrpServerConfig) -> str:
    """Generiert eine vollstaendige frps.toml aus der DB-Konfiguration."""
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

    lines.extend(_tls_server_block(config))

    return '\n'.join(lines) + '\n'


def generate_frpc_toml(
    config: FrpServerConfig,
    tunnels: list[FrpTunnel],
    frpc_user: str,
    allow_users: list[str] | None = None,
) -> str:
    """Generiert eine frpc.toml fuer einen Zielhost.

    Args:
        config: Die zentrale frps-Konfiguration.
        tunnels: Alle Tunnel die zu diesem Host gehoeren.
        frpc_user: Der frpc user-Identifier (z.B. "k01-lnx1").
    """
    import json as _json

    lines = [
        f'serverAddr = "{config.server_addr}"',
        f'serverPort = {config.bind_port}',
        f'user = "{frpc_user}"',
        '',
        '[auth]',
        'method = "token"',
        '',
        '[auth.token]',
        f'token = "{config.auth_token}"',
    ]

    lines.extend(_tls_client_block(config, frpc_user))

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
) -> str:
    """Generiert eine Visitor-frpc.toml fuer den Admin-PC.

    Aggregiert alle STCP-Tunnel und erzeugt je einen [[visitors]]-Block.
    """
    lines = [
        f'serverAddr = "{config.server_addr}"',
        f'serverPort = {config.bind_port}',
        f'user = "{visitor_user}"',
        '',
        '[auth]',
        'method = "token"',
        '',
        '[auth.token]',
        f'token = "{config.auth_token}"',
    ]

    lines.extend(_tls_client_block(config, visitor_user))

    stcp_tunnels = [t for t in tunnels if t.tunnel_type == "stcp" and t.enabled]
    stcp_tunnels.sort(key=lambda t: t.visitor_port or 0)

    for tunnel in stcp_tunnels:
        lines.append('')
        lines.append('[[visitors]]')
        lines.append(f'name = "{tunnel.name}-visitor"')
        lines.append(f'type = "stcp"')
        lines.append(f'serverName = "{tunnel.name}"')
        lines.append(f'secretKey = "{tunnel.secret_key}"')
        lines.append(f'bindAddr = "127.0.0.1"')
        lines.append(f'bindPort = {tunnel.visitor_port}')

    return '\n'.join(lines) + '\n'
