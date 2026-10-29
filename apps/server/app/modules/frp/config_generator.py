# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generates FRP configuration files (TOML) from the DB models."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.modules.frp.schemas import (
    PORT_MAX,
    PORT_MIN,
    _check_tunnel_extra_config,
    is_plugin_key,
)

if TYPE_CHECKING:
    from app.modules.frp.models import FrpServerConfig, FrpTunnel

logger = logging.getLogger(__name__)

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
# frps' own bindPort default (ServerConfig.Complete, v0.69.1) and the schema's.
_DEFAULT_BIND_PORT = 7000
# Always cap ports per client: without it frps defaults to unlimited, so a
# compromised/malicious enrolled agent could register arbitrarily many proxies.
# 16 is generous for a normal host (SSH/RDP/web + a few services) yet bounds the
# blast radius; an operator can raise it per config (3.34).
_DEFAULT_MAX_PORTS_PER_CLIENT = 16


# The schema keeps new values in range (R-0411), but rows written before that
# were never checked and are not migrated. frps exits on a port outside 0..65535
# (validation.ValidatePort, v0.69.1), `bindPort = None` is no TOML at all, and a
# negative maxPortsPerClient lifts the cap (frps enforces it only while > 0). So
# the generator reads these fields through the guards below and logs each
# replacement; the stored row stays as it is.
def _is_port(value: int | None) -> bool:
    return value is not None and PORT_MIN <= value <= PORT_MAX


def frps_bind_port(config: FrpServerConfig) -> int:
    """The bindPort the generated files carry for this config, without the warning
    _bind_port logs where it writes them."""
    return config.bind_port if _is_port(config.bind_port) else _DEFAULT_BIND_PORT


def _bind_port(config: FrpServerConfig) -> int:
    if not _is_port(config.bind_port):
        logger.warning(
            "FRP server config: bind_port %r is outside %d-%d, using %d",
            config.bind_port,
            PORT_MIN,
            PORT_MAX,
            _DEFAULT_BIND_PORT,
        )
    return frps_bind_port(config)


def _optional_port(config: FrpServerConfig, field: str) -> int | None:
    """A port that may be unset (None = its line is left out)."""
    value = getattr(config, field)
    if value is None or _is_port(value):
        return value
    logger.warning(
        "FRP server config: %s %r is outside %d-%d, left out", field, value, PORT_MIN, PORT_MAX
    )
    return None


def _max_ports_per_client(config: FrpServerConfig) -> int:
    value = config.max_ports_per_client
    if value is not None and value < 0:
        logger.warning(
            "FRP server config: max_ports_per_client %r is negative, using %d",
            value,
            _DEFAULT_MAX_PORTS_PER_CLIENT,
        )
        return _DEFAULT_MAX_PORTS_PER_CLIENT
    return value or _DEFAULT_MAX_PORTS_PER_CLIENT


def without_secretless_stcp(tunnels: list[FrpTunnel]) -> list[FrpTunnel]:
    """Leave out stcp tunnels that have no secret.

    Proxy and visitor must carry the same secretKey; writing one without it would
    emit secretKey "None" or "". Skipping it keeps the other tunnels of the host
    and the provision hash intact, where raising would stop the whole config."""
    kept = []
    for tunnel in tunnels:
        if tunnel.tunnel_type == "stcp" and not tunnel.secret_key:
            logger.warning(
                "FRP tunnel %s is stcp without a secret, left out of the config", tunnel.name
            )
            continue
        kept.append(tunnel)
    return kept


def _stored_extra_config(tunnel: FrpTunnel) -> dict | None:
    """The extra_config generate_frpc_toml reads: the column holds JSON text, a caller
    may pass a dict, and an unset one is {}. None for text that is no JSON object."""
    extra = tunnel.extra_config
    if not extra:
        return {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except ValueError:
            return None
    return extra if isinstance(extra, dict) else None


def _api_takes(extra: dict) -> bool:
    try:
        _check_tunnel_extra_config(extra)
    except ValueError:
        return False
    return True


# The sync and the hash poll both run this for every host, every few seconds; a row that stays
# refused would warn each time. One warning per (tunnel name, refused keys), forgotten when the
# set grows past the bound (the next poll then warns once more, which is harmless).
_refused_warned: set[tuple[str, tuple[str, ...] | None]] = set()
_REFUSED_WARNED_MAX = 1024


def _first_warning(name: str, refused: tuple[str, ...] | None) -> bool:
    if len(_refused_warned) >= _REFUSED_WARNED_MAX:
        _refused_warned.clear()
    if (name, refused) in _refused_warned:
        return False
    _refused_warned.add((name, refused))
    return True


def without_refused_extra_config(tunnels: list[FrpTunnel]) -> list[FrpTunnel]:
    """Leave out tunnels whose stored extra_config the API would refuse today.

    The API holds a tunnel's extra_config to _check_tunnel_extra_config (bare keys, none
    of the plugin family, scalar values without TOML breakers, 64-bit integers, no key that
    clashes with a proxy field or another key); rows stored before those
    checks stay as they are, and text that is no JSON object counts as refused. The
    generator writes each entry verbatim into the proxy, so such a row would make a
    frpc.toml that does not hold for the whole host; skipping the tunnel keeps the other
    tunnels of the host. The warning names the keys (repr, so it stays one line), never
    their values, and says it once per tunnel and key set, not at every poll."""
    kept = []
    for tunnel in tunnels:
        extra = _stored_extra_config(tunnel)
        if extra is None:
            if _first_warning(tunnel.name, None):
                logger.warning(
                    "FRP tunnel %r has an extra_config that is no JSON object, "
                    "left out of the config",
                    tunnel.name,
                )
            continue
        refused = sorted(key for key, value in extra.items() if not _api_takes({key: value}))
        if not refused and not _api_takes(extra):
            # Each key passes alone, the keys together clash.
            refused = sorted(extra)
        if refused:
            if _first_warning(tunnel.name, tuple(refused)):
                logger.warning(
                    "FRP tunnel %r has %s in extra_config, left out of the config: %s",
                    tunnel.name,
                    "plugin keys"
                    if all(is_plugin_key(key) for key in refused)
                    else "entries the API refuses",
                    ", ".join(repr(key) for key in refused),
                )
            continue
        kept.append(tunnel)
    return kept


def without_unbindable_visitor(tunnels: list[FrpTunnel]) -> list[FrpTunnel]:
    """Leave out stcp tunnels whose visitor_port is no port from 1 to 65535.

    The schema keeps new values in range (R-0533); rows from before, and the stcp rows
    migration f1a2b3c4d5e6 left without a port, stay as they are. Written as bindPort,
    such a value makes the desktop refuse the whole visitor TOML, and None is no TOML
    at all. Only the visitor is left out: the agent's frpc config keeps the proxy."""
    kept = []
    for tunnel in tunnels:
        if tunnel.tunnel_type == "stcp" and not _is_port(tunnel.visitor_port):
            logger.warning(
                "FRP tunnel %s: visitor_port %r is outside %d-%d, left out of the visitor config",
                tunnel.name,
                tunnel.visitor_port,
                PORT_MIN,
                PORT_MAX,
            )
            continue
        kept.append(tunnel)
    return kept


def without_unreachable_local(tunnels: list[FrpTunnel]) -> list[FrpTunnel]:
    """Leave out tunnels whose local_port is no port from 1 to 65535.

    frpc refuses the whole config for a localPort outside 0..65535 (ValidatePort,
    v0.69.1), which took down every tunnel of the host, and 0 is no target. The API
    holds new values in range (R-0560); rows from before stay as they are. Only the
    proxy is left out, the visitor config is untouched."""
    kept = []
    for tunnel in tunnels:
        if not _is_port(tunnel.local_port):
            logger.warning(
                "FRP tunnel %s: local_port %r is outside %d-%d, left out of the frpc config",
                tunnel.name,
                tunnel.local_port,
                PORT_MIN,
                PORT_MAX,
            )
            continue
        kept.append(tunnel)
    return kept


def active_tunnels(tunnels: list[FrpTunnel]) -> list[FrpTunnel]:
    """The tunnels generate_frpc_toml writes as [[proxies]]: enabled, stcp only with
    a secret, a local_port from 1 to 65535 (without_unreachable_local), and none whose
    stored extra_config the API would refuse (without_refused_extra_config). Without an active tunnel, the text carries no frps
    token; config-hash, config download and provisioning bundle all come from that
    text, so they can't drift.

    Sorted by name (unique): the callers query without ORDER BY, and Postgres
    returns rows in physical order, which an UPDATE of a column outside the config
    (connection_id) changes. Unsorted, the hash would change with the same config."""
    return sorted(
        without_refused_extra_config(
            without_unreachable_local(without_secretless_stcp([t for t in tunnels if t.enabled]))
        ),
        key=lambda t: t.name,
    )


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
        f"bindPort = {_bind_port(config)}",
    ]

    vhost_https_port = _optional_port(config, "vhost_https_port")
    if vhost_https_port:
        lines.append(f"vhostHTTPSPort = {vhost_https_port}")

    if config.subdomain_host:
        lines.append(f'subDomainHost = "{config.subdomain_host}"')

    lines.append(f"maxPortsPerClient = {_max_ports_per_client(config)}")

    lines.append("detailedErrorsToClient = false")
    lines.append("")

    # Dashboard
    dashboard_port = _optional_port(config, "dashboard_port")
    if dashboard_port:
        # Bind all interfaces, not loopback: in compose the frps supervisor asks the dashboard
        # over loopback inside the frps container, which 0.0.0.0 covers, but with
        # FRPS_DASHBOARD_URL (frps in another topology) the server asks it over the network.
        # The dashboard port is never published in compose, and frps sits alone in the
        # network frpedge, so neither the host nor the public internet reaches it (4.6).
        lines.append('webServer.addr = "0.0.0.0"')
        lines.append(f"webServer.port = {dashboard_port}")
        if config.dashboard_user:
            lines.append(f'webServer.user = "{config.dashboard_user}"')
        if config.dashboard_password:
            lines.append(f'webServer.password = "{config.dashboard_password}"')
        lines.append("")

    # Auth
    lines.append('auth.method = "token"')
    lines.append(f'auth.token = "{config.auth_token}"')

    # Operator-supplied extra frps.toml fields: keys of extra_config.ALLOWED_KEYS with values
    # that pass value_allowed. _check_frps_extra_config holds the API to that and the startup
    # check in main.py the stored rows, so they can be emitted verbatim.
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

    Without an active tunnel (active_tunnels) the result is the common part without
    the frps token and without [[proxies]]: such a host needs no frps credentials,
    and an agent that applies the text keeps no tunnel up. Config hash and config
    download of the sync both come from here, so they carry the same text.

    Args:
        config: The central frps configuration.
        tunnels: All tunnels belonging to this host.
        frpc_user: The frpc user identifier (e.g. "k01-lnx1").
    """
    active = active_tunnels(tunnels)
    lines = [
        f'serverAddr = "{config.server_addr}"',
        f"serverPort = {_bind_port(config)}",
        f'user = "{frpc_user}"',
        "",
        'auth.method = "token"',
    ]
    if active:
        lines.append(f'auth.token = "{config.auth_token}"')

    lines.extend(_tls_agent_block())

    for tunnel in active:
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

    Aggregates all STCP tunnels with a secret and a usable visitor port and emits
    one [[visitors]] block each. The TLS block points at the desktop's enrolled
    identity (F2), which it supplies itself.
    """
    lines = [
        f'serverAddr = "{config.server_addr}"',
        f"serverPort = {_bind_port(config)}",
        f'user = "{visitor_user}"',
        "",
        'auth.method = "token"',
        f'auth.token = "{config.auth_token}"',
    ]

    lines.extend(_tls_client_block())

    stcp_tunnels = without_unbindable_visitor(
        without_secretless_stcp([t for t in tunnels if t.tunnel_type == "stcp" and t.enabled])
    )
    stcp_tunnels.sort(key=lambda t: t.visitor_port)

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
