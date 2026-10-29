# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the FRP config generator: frps.toml, frpc.toml, visitor.toml."""

import json
import logging
import tomllib
from pathlib import Path
from types import SimpleNamespace

from app.modules.frp.config_generator import (
    generate_frpc_toml,
    generate_frps_toml,
    generate_visitor_toml,
    without_refused_extra_config,
)

AGENT_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "agent"
    / "internal"
    / "frpc"
    / "testdata"
    / "server_frpc.toml"
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
        extra_config=None,
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
        assert "bindPort = 7000" in toml
        assert 'auth.token = "secret-token"' in toml
        assert "[transport.tls]" in toml
        assert "force = true" in toml

    def test_tls_paths_match_ca_issuer_filenames(self):
        # 6.80: pin the frps mTLS cert paths against the filenames ca-issuer's ensure_frps_cert writes
        # (ca.crt / frps.crt / frps.key under /etc/frp-pki, the compose ro-mount). frpc/visitor have
        # explicit path contracts but frps had none — renaming _FRPS_CERT_DIR or the leaf files is
        # exactly the drift class that hit the identity/ replace, and would go unnoticed frps-side.
        toml = generate_frps_toml(_make_config())
        assert 'certFile = "/etc/frp-pki/frps.crt"' in toml
        assert 'keyFile = "/etc/frp-pki/frps.key"' in toml
        assert 'trustedCaFile = "/etc/frp-pki/ca.crt"' in toml

    def test_max_ports_per_client_defaults_when_unset(self):
        # 3.34: never leave it unlimited — an unset value emits the bounded default.
        config = _make_config(max_ports_per_client=None)
        assert "maxPortsPerClient = 16" in generate_frps_toml(config)

    def test_max_ports_per_client_honors_explicit_value(self):
        config = _make_config(max_ports_per_client=64)
        assert "maxPortsPerClient = 64" in generate_frps_toml(config)

    def test_dashboard_included(self):
        config = _make_config(dashboard_port=7500, dashboard_user="admin", dashboard_password="pw")
        toml = generate_frps_toml(config)
        # All interfaces: the supervisor asks over loopback inside the frps container, the
        # server with FRPS_DASHBOARD_URL over the network (4.6).
        assert 'webServer.addr = "0.0.0.0"' in toml
        assert "webServer.port = 7500" in toml
        assert 'webServer.user = "admin"' in toml
        assert 'webServer.password = "pw"' in toml

    def test_no_dashboard_when_port_none(self):
        config = _make_config(dashboard_port=None)
        toml = generate_frps_toml(config)
        assert "webServer.port" not in toml

    def test_vhost_https(self):
        config = _make_config(vhost_https_port=443)
        toml = generate_frps_toml(config)
        assert "vhostHTTPSPort = 443" in toml

    def test_subdomain_host(self):
        config = _make_config(subdomain_host="ops.example.net")
        toml = generate_frps_toml(config)
        assert 'subDomainHost = "ops.example.net"' in toml

    def test_extra_config_emitted(self):
        # 1.28: extra_config is validated + stored but was never emitted.
        config = _make_config(
            extra_config=json.dumps(
                {"maxPoolCount": 5, "transport.tcpMux": True, "custom.note": "hi"}
            )
        )
        toml = generate_frps_toml(config)
        assert "maxPoolCount = 5" in toml
        assert "transport.tcpMux = true" in toml  # bool -> lowercase TOML literal
        assert 'custom.note = "hi"' in toml  # str -> quoted

    def test_no_extra_config_lines_when_none(self):
        toml = generate_frps_toml(_make_config(extra_config=None))
        assert "maxPoolCount" not in toml


class TestGenerateFrpcToml:
    def test_basic_stcp_tunnel(self):
        config = _make_config()
        tunnel = _make_tunnel()
        toml = generate_frpc_toml(config, [tunnel], "srv1")
        assert 'user = "srv1"' in toml
        assert "[[proxies]]" in toml
        assert 'name = "srv1-ssh"' in toml
        assert 'type = "stcp"' in toml
        assert "localPort = 22" in toml
        assert 'secretKey = "tunnel-secret"' in toml

    def test_disabled_tunnel_excluded(self):
        config = _make_config()
        tunnel = _make_tunnel(enabled=False)
        toml = generate_frpc_toml(config, [tunnel], "srv1")
        assert "[[proxies]]" not in toml

    def test_https_tunnel_custom_domains(self):
        config = _make_config()
        tunnel = _make_tunnel(
            tunnel_type="https",
            custom_domains="app.example.com, api.example.com",
            secret_key=None,
        )
        toml = generate_frpc_toml(config, [tunnel], "web1")
        assert 'customDomains = ["app.example.com", "api.example.com"]' in toml
        assert "secretKey" not in toml

    def test_allow_users_override(self):
        config = _make_config()
        tunnel = _make_tunnel()
        toml = generate_frpc_toml(config, [tunnel], "srv1", allow_users=["user-a", "user-b"])
        assert 'allowUsers = ["user-a", "user-b"]' in toml

    def test_allow_users_fallback_is_ops_admin_not_wildcard(self):
        # 6.146: an empty allow_users falls back to the ops-admin visitor, NOT "*" — the fail-closed
        # safety net get_allow_users relies on. A "*" here would let every visitor reach every tunnel.
        config = _make_config()
        tunnel = _make_tunnel()
        toml = generate_frpc_toml(config, [tunnel], "srv1")  # no allow_users -> fallback
        assert 'allowUsers = ["ops-admin"]' in toml
        assert 'allowUsers = ["*"]' not in toml

    def test_extra_config_applied(self):
        config = _make_config()
        tunnel = _make_tunnel(extra_config='{"bandwidth": "10MB", "useCompression": true}')
        toml = generate_frpc_toml(config, [tunnel], "srv1")
        assert 'bandwidth = "10MB"' in toml
        assert "useCompression = true" in toml

    def test_tls_agent_block_uses_enrolled_identity(self):
        # A7: the agent's frpc presents its enrolled tunnel cert (A4), not a
        # server-minted per-user cert under /etc/frp/pki.
        config = _make_config()
        toml = generate_frpc_toml(config, [], "client1")
        assert "[transport.tls]" in toml
        assert "enable = true" in toml
        assert 'certFile = "/etc/adminhelper/identity/agent.crt"' in toml
        assert 'keyFile = "/etc/adminhelper/identity/agent.key"' in toml
        assert 'trustedCaFile = "/etc/adminhelper/identity/ca.crt"' in toml
        assert "/etc/frp/pki" not in toml

    def test_multiple_tunnels(self):
        config = _make_config()
        tunnels = [
            _make_tunnel(name="ssh", local_port=22),
            _make_tunnel(name="rdp", local_port=3389, tunnel_type="stcp"),
        ]
        toml = generate_frpc_toml(config, tunnels, "srv1")
        assert toml.count("[[proxies]]") == 2

    def test_agent_fixture_is_the_generator_output(self):
        """The agent applies a server frpc.toml only in the form this generator writes
        (checkServerConfig, apps/agent/internal/frpc/servertoml.go), and its tests check that
        against this fixture. When the generator's output changes, this test fails until the
        fixture and the agent's check follow; otherwise agents would refuse the new text and
        keep their old tunnels."""
        config = _make_config(
            server_addr="203.0.113.10",
            bind_port=7000,
            auth_token="frps-token-placeholder",
        )
        # Not in name order: the order in the fixture is the one active_tunnels sorts to.
        tunnels = [
            _make_tunnel(
                name="host-01-web",
                tunnel_type="https",
                protocol="web",
                local_port=443,
                secret_key=None,
                custom_domains="web.example, www.web.example",
            ),
            _make_tunnel(
                name="host-01-ssh",
                local_port=22,
                secret_key="stcp-secret-placeholder",
                extra_config=json.dumps(
                    {
                        "transport.bandwidthLimit": "1MB",
                        "transport.useEncryption": True,
                        "healthCheck.intervalSeconds": 10,
                    }
                ),
            ),
        ]
        toml = generate_frpc_toml(config, tunnels, "host-01", ["ops-admin", "ops-backup"])
        # Bytes, not read_text: universal newlines would turn \r\n into \n, and the agent
        # refuses a \r.
        assert toml == AGENT_FIXTURE.read_bytes().decode("utf-8")


class TestGenerateVisitorToml:
    def test_basic_visitor(self):
        config = _make_config()
        tunnel = _make_tunnel()
        toml = generate_visitor_toml(config, [tunnel])
        assert 'user = "ops-admin"' in toml
        assert "[[visitors]]" in toml
        assert 'name = "srv1-ssh-visitor"' in toml
        assert 'serverName = "srv1-ssh"' in toml
        assert 'serverUser = "srv1"' in toml
        assert "bindPort = 6001" in toml

    def test_non_stcp_excluded(self):
        config = _make_config()
        tunnel = _make_tunnel(tunnel_type="https")
        toml = generate_visitor_toml(config, [tunnel])
        assert "[[visitors]]" not in toml

    def test_disabled_excluded(self):
        config = _make_config()
        tunnel = _make_tunnel(enabled=False)
        toml = generate_visitor_toml(config, [tunnel])
        assert "[[visitors]]" not in toml

    def test_custom_visitor_user(self):
        config = _make_config()
        toml = generate_visitor_toml(config, [], visitor_user="custom-admin")
        assert 'user = "custom-admin"' in toml

    def test_tls_block_uses_enrolled_identity(self):
        # F2: the visitor presents the desktop's enrolled access identity, exported
        # under the {{IDENTITY_DIR}} placeholder the desktop replaces with an
        # absolute path — not a server-minted cert under the old /etc/frp/pki CA.
        # The literal placeholder is the server<->desktop contract (frpc.rs rewrites
        # exactly this token); keep it in lockstep with IDENTITY_DIR_PLACEHOLDER.
        config = _make_config()
        toml = generate_visitor_toml(config, [])
        assert "[transport.tls]" in toml
        assert "enable = true" in toml
        assert 'trustedCaFile = "{{IDENTITY_DIR}}/ca.crt"' in toml
        assert 'certFile = "{{IDENTITY_DIR}}/cert.pem"' in toml
        assert 'keyFile = "{{IDENTITY_DIR}}/key.pem"' in toml
        assert "/etc/frp/pki" not in toml


class TestLocalPortOutsideRange:
    # R-0560: frpc refuses the whole config for a localPort outside 0..65535, so one stored
    # row cost every tunnel of the host. Only that proxy is left out, with a warning.
    def test_frpc_skips_local_port_outside_range(self, caplog):
        import logging

        bad = [
            _make_tunnel(name=f"bad-{i}", local_port=port)
            for i, port in enumerate((0, -1, 65536, 70000))
        ]
        ok = _make_tunnel(name="ok", local_port=22)
        with caplog.at_level(logging.WARNING):
            toml = generate_frpc_toml(_make_config(), [*bad, ok], "srv1")
        assert toml.count("[[proxies]]") == 1
        assert toml == generate_frpc_toml(_make_config(), [ok], "srv1")
        warned = [r.getMessage() for r in caplog.records if "local_port" in r.getMessage()]
        for tunnel in bad:
            assert any(
                tunnel.name in m and repr(tunnel.local_port) in m and "left out" in m
                for m in warned
            ), (tunnel.name, warned)

    def test_frpc_keeps_the_edges(self):
        tunnels = [
            _make_tunnel(name="low", local_port=1),
            _make_tunnel(name="high", local_port=65535),
        ]
        toml = generate_frpc_toml(_make_config(), tunnels, "srv1")
        assert toml.count("[[proxies]]") == 2
        assert "localPort = 1\n" in toml and "localPort = 65535\n" in toml

    def test_frpc_with_only_bad_local_ports_is_the_empty_config(self):
        tunnels = [_make_tunnel(name="bad", local_port=70000)]
        assert generate_frpc_toml(_make_config(), tunnels, "srv1") == generate_frpc_toml(
            _make_config(), [], "srv1"
        )


class TestStcpWithoutSecret:
    # An stcp tunnel without a secret is left out of the frpc and visitor TOML (and logged)
    # instead of being written with secretKey "None" or ""; the tunnels next to it are untouched.
    def test_frpc_skips_stcp_without_secret(self, caplog):
        import logging

        tunnels = [
            _make_tunnel(name="no-secret", secret_key=None),
            _make_tunnel(name="empty-secret", secret_key=""),
            _make_tunnel(name="ok", secret_key="tunnel-secret"),
        ]
        with caplog.at_level(logging.WARNING):
            toml = generate_frpc_toml(_make_config(), tunnels, "srv1")
        assert "no-secret" not in toml and "empty-secret" not in toml
        assert "None" not in toml
        assert 'secretKey = ""' not in toml
        assert toml.count("[[proxies]]") == 1
        assert toml == generate_frpc_toml(_make_config(), [tunnels[2]], "srv1")
        warned = " ".join(r.getMessage() for r in caplog.records)
        assert "no-secret" in warned and "empty-secret" in warned

    def test_visitor_skips_stcp_without_secret(self, caplog):
        import logging

        tunnels = [
            _make_tunnel(name="no-secret", secret_key=None, visitor_port=6002),
            _make_tunnel(name="empty-secret", secret_key="", visitor_port=6003),
            _make_tunnel(name="ok", secret_key="tunnel-secret"),
        ]
        with caplog.at_level(logging.WARNING):
            toml = generate_visitor_toml(_make_config(), tunnels)
        assert "no-secret" not in toml and "empty-secret" not in toml
        assert "None" not in toml
        assert 'secretKey = ""' not in toml
        assert toml.count("[[visitors]]") == 1
        assert toml == generate_visitor_toml(_make_config(), [tunnels[2]])
        warned = " ".join(r.getMessage() for r in caplog.records)
        assert "no-secret" in warned and "empty-secret" in warned


class TestStcpWithoutVisitorPort:
    # R-0533: a stored visitor_port outside 1-65535 (rows from before the schema bounded it) or
    # none at all (migration f1a2b3c4d5e6) is left out of the visitor TOML and logged, instead of
    # a bindPort the desktop refuses the whole TOML for, or `bindPort = None`, which is no TOML.
    # The agent's frpc config keeps the tunnel's proxy.
    BAD_PORTS = (None, 0, -1, 65536, 70000)

    def _tunnels(self):
        bad = [_make_tunnel(name=f"bad-{i}", visitor_port=p) for i, p in enumerate(self.BAD_PORTS)]
        return [*bad, _make_tunnel(name="ok", visitor_port=6001)]

    def test_visitor_skips_port_outside_range(self, caplog):
        import logging

        tunnels = self._tunnels()
        with caplog.at_level(logging.WARNING, logger="app.modules.frp.config_generator"):
            toml = generate_visitor_toml(_make_config(), tunnels)
        assert toml.count("[[visitors]]") == 1
        assert toml == generate_visitor_toml(_make_config(), [tunnels[-1]])
        visitors = tomllib.loads(toml)["visitors"]
        assert [(v["name"], v["bindPort"]) for v in visitors] == [("ok-visitor", 6001)]
        warned = [r.getMessage() for r in caplog.records]
        assert len(warned) == len(self.BAD_PORTS), warned
        for tunnel in tunnels[:-1]:
            assert any(
                tunnel.name in m and f"visitor_port {tunnel.visitor_port!r}" in m for m in warned
            ), (tunnel.name, warned)

    def test_visitor_keeps_the_edge_ports(self):
        tunnels = [
            _make_tunnel(name="high", visitor_port=65535),
            _make_tunnel(name="low", visitor_port=1),
        ]
        visitors = tomllib.loads(generate_visitor_toml(_make_config(), tunnels))["visitors"]
        assert [(v["name"], v["bindPort"]) for v in visitors] == [
            ("low-visitor", 1),
            ("high-visitor", 65535),
        ]

    def test_frpc_keeps_every_proxy(self, caplog):
        import logging

        tunnels = self._tunnels()
        with caplog.at_level(logging.WARNING, logger="app.modules.frp.config_generator"):
            toml = generate_frpc_toml(_make_config(), tunnels, "srv1")
        proxies = tomllib.loads(toml)["proxies"]
        assert sorted(p["name"] for p in proxies) == sorted(t.name for t in tunnels)
        assert not caplog.records, [r.getMessage() for r in caplog.records]


class TestRefusedExtraConfigWarning:
    # R-0895: the sync and the hash poll run the filter every few seconds, so a stored row the
    # API would refuse warned at each run. It warns once per tunnel and key set.
    @staticmethod
    def _warnings(caplog):
        return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]

    def test_a_refused_row_warns_once_however_often_it_is_filtered(self, caplog):
        tunnel = _make_tunnel(name="bad", extra_config='{"plugin.type": "x"}')
        with caplog.at_level(logging.WARNING, logger="app.modules.frp.config_generator"):
            for _ in range(3):
                assert without_refused_extra_config([tunnel]) == []
        assert len(self._warnings(caplog)) == 1

    def test_changed_keys_warn_again(self, caplog):
        tunnel = _make_tunnel(name="bad", extra_config='{"plugin.type": "x"}')
        with caplog.at_level(logging.WARNING, logger="app.modules.frp.config_generator"):
            without_refused_extra_config([tunnel])
            tunnel.extra_config = '{"localPort": 1}'
            without_refused_extra_config([tunnel])
        assert len(self._warnings(caplog)) == 2

    def test_the_wording_names_plugin_keys_only_for_plugin_keys(self, caplog):
        plugin = _make_tunnel(name="p", extra_config='{"plugin.type": "x"}')
        mixed = _make_tunnel(name="m", extra_config='{"plugin.type": "x", "localPort": 1}')
        text = _make_tunnel(name="t", extra_config="not json")
        with caplog.at_level(logging.WARNING, logger="app.modules.frp.config_generator"):
            without_refused_extra_config([plugin, mixed, text])
        warned = self._warnings(caplog)
        by_tunnel = {name: m for name in ("p", "m", "t") for m in warned if f"'{name}'" in m}
        assert "has plugin keys in extra_config" in by_tunnel["p"]
        assert "has entries the API refuses in extra_config" in by_tunnel["m"]
        assert "no JSON object" in by_tunnel["t"]

    def test_a_row_the_api_takes_is_kept_without_a_warning(self, caplog):
        tunnel = _make_tunnel(name="ok", extra_config='{"bandwidth": "10MB"}')
        with caplog.at_level(logging.WARNING, logger="app.modules.frp.config_generator"):
            assert without_refused_extra_config([tunnel]) == [tunnel]
        assert not self._warnings(caplog)
