# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the FRP config generator: frps.toml, frpc.toml, visitor.toml."""

from types import SimpleNamespace
from app.modules.frp.config_generator import (
    generate_frps_toml,
    generate_frpc_toml,
    generate_visitor_toml,
)


def _make_config(**overrides):
    """Creates a FrpServerConfig-like object for tests."""
    defaults = dict(
        server_addr="frps.example.net",
        bind_port=7000,
        auth_token="secret-token",
        vhost_https_port=None,
        subdomain_host=None,
        max_ports_per_client=None,
        dashboard_port=None,
        dashboard_user=None,
        dashboard_password=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_tunnel(**overrides):
    """Creates a FrpTunnel-like object for tests."""
    defaults = dict(
        name="srv1-ssh",
        tunnel_type="stcp",
        protocol="ssh",
        local_ip="127.0.0.1",
        local_port=22,
        secret_key="tunnel-secret",
        custom_domains=None,
        visitor_port=6001,
        enabled=True,
        extra_config=None,
        target_server=SimpleNamespace(name="srv1"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestGenerateFrpsToml:
    def test_minimal_config(self):
        config = _make_config()
        toml = generate_frps_toml(config)
        assert 'bindPort = 7000' in toml
        assert 'auth.token = "secret-token"' in toml
        assert '[transport.tls]' in toml
        assert 'force = true' in toml

    def test_dashboard_included(self):
        config = _make_config(dashboard_port=7500, dashboard_user="admin", dashboard_password="pw")
        toml = generate_frps_toml(config)
        assert 'webServer.port = 7500' in toml
        assert 'webServer.user = "admin"' in toml
        assert 'webServer.password = "pw"' in toml

    def test_no_dashboard_when_port_none(self):
        config = _make_config(dashboard_port=None)
        toml = generate_frps_toml(config)
        assert 'webServer.port' not in toml

    def test_vhost_https(self):
        config = _make_config(vhost_https_port=443)
        toml = generate_frps_toml(config)
        assert 'vhostHTTPSPort = 443' in toml

    def test_subdomain_host(self):
        config = _make_config(subdomain_host="ops.example.net")
        toml = generate_frps_toml(config)
        assert 'subDomainHost = "ops.example.net"' in toml


class TestGenerateFrpcToml:
    def test_basic_stcp_tunnel(self):
        config = _make_config()
        tunnel = _make_tunnel()
        toml = generate_frpc_toml(config, [tunnel], "srv1")
        assert 'user = "srv1"' in toml
        assert '[[proxies]]' in toml
        assert 'name = "srv1-ssh"' in toml
        assert 'type = "stcp"' in toml
        assert 'localPort = 22' in toml
        assert 'secretKey = "tunnel-secret"' in toml

    def test_disabled_tunnel_excluded(self):
        config = _make_config()
        tunnel = _make_tunnel(enabled=False)
        toml = generate_frpc_toml(config, [tunnel], "srv1")
        assert '[[proxies]]' not in toml

    def test_https_tunnel_custom_domains(self):
        config = _make_config()
        tunnel = _make_tunnel(
            tunnel_type="https",
            custom_domains="app.example.com, api.example.com",
            secret_key=None,
        )
        toml = generate_frpc_toml(config, [tunnel], "web1")
        assert 'customDomains = ["app.example.com", "api.example.com"]' in toml
        assert 'secretKey' not in toml

    def test_allow_users_override(self):
        config = _make_config()
        tunnel = _make_tunnel()
        toml = generate_frpc_toml(config, [tunnel], "srv1", allow_users=["user-a", "user-b"])
        assert 'allowUsers = ["user-a", "user-b"]' in toml

    def test_extra_config_applied(self):
        config = _make_config()
        tunnel = _make_tunnel(extra_config='{"bandwidth": "10MB", "useCompression": true}')
        toml = generate_frpc_toml(config, [tunnel], "srv1")
        assert 'bandwidth = "10MB"' in toml
        assert 'useCompression = true' in toml

    def test_tls_client_block(self):
        config = _make_config()
        toml = generate_frpc_toml(config, [], "client1")
        assert '[transport.tls]' in toml
        assert 'enable = true' in toml
        assert 'certFile = "/etc/frp/pki/client1.crt"' in toml

    def test_multiple_tunnels(self):
        config = _make_config()
        tunnels = [
            _make_tunnel(name="ssh", local_port=22),
            _make_tunnel(name="rdp", local_port=3389, tunnel_type="stcp"),
        ]
        toml = generate_frpc_toml(config, tunnels, "srv1")
        assert toml.count('[[proxies]]') == 2


class TestGenerateVisitorToml:
    def test_basic_visitor(self):
        config = _make_config()
        tunnel = _make_tunnel()
        toml = generate_visitor_toml(config, [tunnel])
        assert 'user = "ops-admin"' in toml
        assert '[[visitors]]' in toml
        assert 'name = "srv1-ssh-visitor"' in toml
        assert 'serverName = "srv1-ssh"' in toml
        assert 'serverUser = "srv1"' in toml
        assert 'bindPort = 6001' in toml

    def test_non_stcp_excluded(self):
        config = _make_config()
        tunnel = _make_tunnel(tunnel_type="https")
        toml = generate_visitor_toml(config, [tunnel])
        assert '[[visitors]]' not in toml

    def test_disabled_excluded(self):
        config = _make_config()
        tunnel = _make_tunnel(enabled=False)
        toml = generate_visitor_toml(config, [tunnel])
        assert '[[visitors]]' not in toml

    def test_custom_visitor_user(self):
        config = _make_config()
        toml = generate_visitor_toml(config, [], visitor_user="custom-admin")
        assert 'user = "custom-admin"' in toml
