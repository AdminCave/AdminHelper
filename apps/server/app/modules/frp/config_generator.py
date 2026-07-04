# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generates FRP configuration files (TOML) from the DB models."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.frp.models import FrpServerConfig, FrpTunnel

# Where frps finds its TLS material — the volume the ca-issuer provisions under
# the tunnel intermediate (A7), no longer the server's self-run FRP CA.
_FRPS_CERT_DIR = "/etc/frp-pki"
# Where the agent's frpc finds its mTLS identity: the cert it enrolled at the
# ca-issuer (A4). The frp tunnel reuses that single tunnel-scoped identity rather
# than a separate server-minted client cert.
_AGENT_IDENTITY_DIR = "/etc/adminhelper/identity"
# Where the desktop STCP visitor finds its mTLS identity: the desktop exports its
# enrolled ACCESS identity (key + cert + CA) from the keyring into a local dir and
# substitutes this placeholder with that absolute path (F2). An explicit token —
# not a bare "identity/" prefix — keeps the server<->desktop contract greppable on
# both sides (see IDENTITY_DIR_PLACEHOLDER in the desktop's frpc.rs) instead of
# hinging on a substring match. frps trusts the access intermediate (ca-issuer
# extra_trust) so this access cert is accepted.
_VISITOR_IDENTITY_DIR = "{{IDENTITY_DIR}}"


def _tls_server_block(
    server_name: str = "frps",
    pki_base_path: str = _FRPS_CERT_DIR,
) -> list[str]:
    """Generates the [transport.tls] block for frps (tunnel-signed cert + chain)."""
    return [
        "",
        "[transport.tls]",
        "force = true",
        f'certFile = "{pki_base_path}/{server_name}.crt"',
        f'keyFile = "{pki_base_path}/{server_name}.key"',
        f'trustedCaFile = "{pki_base_path}/ca.crt"',
    ]


def _tls_agent_block() -> list[str]:
    """Generates the [transport.tls] block for the agent's frpc, pointing at the
    enrolled mTLS identity (A4/A7) — one tunnel-scoped cert for both server pushes
    and the frp tunnel."""
    return [
        "",
        "[transport.tls]",
        "enable = true",
        f'trustedCaFile = "{_AGENT_IDENTITY_DIR}/ca.crt"',
        f'certFile = "{_AGENT_IDENTITY_DIR}/agent.crt"',
        f'keyFile = "{_AGENT_IDENTITY_DIR}/agent.key"',
    ]


def _tls_client_block() -> list[str]:
    """Generates the [transport.tls] block for a STCP visitor (frpc). The desktop
    presents its enrolled ACCESS identity (F2): it exports key/cert/CA from its
    keyring into a local dir and replaces the {{IDENTITY_DIR}} placeholder with
    that absolute path. frps trusts the access intermediate (ca-issuer
    extra_trust), so the access cert is accepted on the frp plane (ADR 0001 D8)."""
    return [
        "",
        "[transport.tls]",
        "enable = true",
        f'trustedCaFile = "{_VISITOR_IDENTITY_DIR}/ca.crt"',
        f'certFile = "{_VISITOR_IDENTITY_DIR}/cert.pem"',
        f'keyFile = "{_VISITOR_IDENTITY_DIR}/key.pem"',
    ]


def generate_frps_toml(config: FrpServerConfig) -> str:
    """Generates a complete frps.toml from the DB configuration."""
    lines = [
        f"bindPort = {config.bind_port}",
    ]

    if config.vhost_https_port:
        lines.append(f"vhostHTTPSPort = {config.vhost_https_port}")

    if config.subdomain_host:
        lines.append(f'subDomainHost = "{config.subdomain_host}"')

    if config.max_ports_per_client:
        lines.append(f"maxPortsPerClient = {config.max_ports_per_client}")

    lines.append("detailedErrorsToClient = false")
    lines.append("")

    # Dashboard
    if config.dashboard_port:
        lines.append('webServer.addr = "127.0.0.1"')
        lines.append(f"webServer.port = {config.dashboard_port}")
        if config.dashboard_user:
            lines.append(f'webServer.user = "{config.dashboard_user}"')
        if config.dashboard_password:
            lines.append(f'webServer.password = "{config.dashboard_password}"')
        lines.append("")

    # Auth
    lines.append('auth.method = "token"')
    lines.append(f'auth.token = "{config.auth_token}"')

    # Operator-supplied extra frps.toml fields (e.g. maxPoolCount, transport.*).
    # _check_extra_config already validated the keys as TOML bare keys and the
    # values as str/bool/int/float, so they can be emitted verbatim.
    extra = json.loads(config.extra_config) if config.extra_config else None
    if extra:
        lines.append("")
        for key, value in extra.items():
            if isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            else:
                lines.append(f"{key} = {value}")

    lines.extend(_tls_server_block())

    return "\n".join(lines) + "\n"


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
    lines = [
        f'serverAddr = "{config.server_addr}"',
        f"serverPort = {config.bind_port}",
        f'user = "{frpc_user}"',
        "",
        'auth.method = "token"',
        f'auth.token = "{config.auth_token}"',
    ]

    lines.extend(_tls_agent_block())

    active_tunnels = [t for t in tunnels if t.enabled]

    for tunnel in active_tunnels:
        lines.append("")
        lines.append("[[proxies]]")
        lines.append(f'name = "{tunnel.name}"')
        lines.append(f'type = "{tunnel.tunnel_type}"')
        lines.append(f'localIP = "{tunnel.local_ip}"')
        lines.append(f"localPort = {tunnel.local_port}")

        if tunnel.tunnel_type == "stcp":
            lines.append(f'secretKey = "{tunnel.secret_key}"')
            users = allow_users if allow_users else ["ops-admin"]
            user_list = ", ".join(f'"{u}"' for u in users)
            lines.append(f"allowUsers = [{user_list}]")

        if tunnel.tunnel_type == "https" and tunnel.custom_domains:
            domains = [d.strip() for d in tunnel.custom_domains.split(",")]
            domain_list = ", ".join(f'"{d}"' for d in domains)
            lines.append(f"customDomains = [{domain_list}]")

        if tunnel.extra_config:
            extra = (
                json.loads(tunnel.extra_config)
                if isinstance(tunnel.extra_config, str)
                else tunnel.extra_config
            )
            for key, value in extra.items():
                if isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                elif isinstance(value, bool):
                    lines.append(f"{key} = {'true' if value else 'false'}")
                else:
                    lines.append(f"{key} = {value}")

    return "\n".join(lines) + "\n"


def generate_visitor_toml(
    config: FrpServerConfig,
    tunnels: list[FrpTunnel],
    visitor_user: str = "ops-admin",
) -> str:
    """Generates a visitor frpc.toml for the admin PC.

    Aggregates all STCP tunnels and emits one [[visitors]] block each. The TLS
    block points at the desktop's enrolled identity (F2), which it supplies itself.
    """
    lines = [
        f'serverAddr = "{config.server_addr}"',
        f"serverPort = {config.bind_port}",
        f'user = "{visitor_user}"',
        "",
        'auth.method = "token"',
        f'auth.token = "{config.auth_token}"',
    ]

    lines.extend(_tls_client_block())

    stcp_tunnels = [t for t in tunnels if t.tunnel_type == "stcp" and t.enabled]
    stcp_tunnels.sort(key=lambda t: t.visitor_port or 0)

    for tunnel in stcp_tunnels:
        # FRP registers proxies as "{agent_user}.{proxy_name}".
        # The visitor must set serverUser to the agent user so that
        # FRP finds the proxy as "{serverUser}.{serverName}".
        agent_user = tunnel.target_server.name if tunnel.target_server else ""

        lines.append("")
        lines.append("[[visitors]]")
        lines.append(f'name = "{tunnel.name}-visitor"')
        lines.append('type = "stcp"')
        lines.append(f'serverName = "{tunnel.name}"')
        if agent_user:
            lines.append(f'serverUser = "{agent_user}"')
        lines.append(f'secretKey = "{tunnel.secret_key}"')
        lines.append('bindAddr = "127.0.0.1"')
        lines.append(f"bindPort = {tunnel.visitor_port}")

    return "\n".join(lines) + "\n"
