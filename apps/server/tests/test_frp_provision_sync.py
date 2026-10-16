# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the agent's frpc sync relies on from the server (R-0398).

`GET /api/frp/provision/{id}/config-hash` answers `{"hash": null}` when no FRP
config exists: the agent reads a 404 as permanent, so a host without FRP would
fail every timer run. With a config but no tunnel the hash stays the one of the
TOML without proxies, because an older agent with a stored hash would read null
as "" and fetch the config again on every run. The 403 of the scope check and
the 404 for an unknown server stay.

The agent puts its own top-level keys (`loginFailExit`, `webServer.*`) in front of
the server text and compares the text before the first `[[proxies]]` to choose
between a reload and a restart. Both hold only while the generator writes neither
key and keeps every common key ahead of the first proxy table.
"""

from __future__ import annotations

import hashlib
import secrets
import tomllib

import pytest

from app.core.auth import hash_api_key
from app.modules.api_keys.models import ApiKey
from app.modules.frp.config_generator import generate_frpc_toml
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.servers.models import Server

# The keys the generator writes into a proxy table; none of them may stand
# ahead of the first [[proxies]], where frpc would read it as a common key.
_PROXY_KEYS = {"name", "type", "localIP", "localPort", "secretKey", "allowUsers", "customDomains"}


def _server(db, sid: str = "srv-sync", name: str = "sync-host") -> Server:
    srv = Server(id=sid, name=name, hostname=f"{name}.example.test")
    db.add(srv)
    db.commit()
    return srv


def _agent_key(db, server_id: str) -> dict[str, str]:
    """The agent's read key, bound to its server as provisioning creates it."""
    raw = f"adminhelper_{secrets.token_urlsafe(16)}"
    db.add(
        ApiKey(
            name=f"agent-{server_id}",
            hashed_key=hash_api_key(raw),
            permission="read",
            server_id=server_id,
        )
    )
    db.commit()
    return {"X-API-Key": raw}


def _frp_config(db) -> FrpServerConfig:
    cfg = FrpServerConfig(
        id="cfg-sync",
        name="Default",
        server_addr="frps.example.test",
        bind_port=7000,
        auth_token="sync-frps-auth-token",
    )
    db.add(cfg)
    db.commit()
    return cfg


def _admin_jwt(client) -> dict[str, str]:
    login = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


class TestConfigHash:
    def test_without_an_frp_config_the_hash_is_null(self, test_client, db_session):
        _server(db_session)
        key = _agent_key(db_session, "srv-sync")
        res = test_client.get("/api/frp/provision/srv-sync/config-hash", headers=key)
        assert res.status_code == 200, res.text
        assert res.json() == {"hash": None}

    def test_without_an_frp_config_the_config_stays_404(self, test_client, db_session):
        _server(db_session)
        key = _agent_key(db_session, "srv-sync")
        res = test_client.get("/api/frp/provision/srv-sync/config", headers=key)
        assert res.status_code == 404, res.text
        assert res.json()["detail"] == "Keine FRP-Config vorhanden"

    def test_a_config_without_tunnels_hashes_the_toml_without_proxies(
        self, test_client, db_session
    ):
        _server(db_session)
        _frp_config(db_session)
        key = _agent_key(db_session, "srv-sync")
        toml = test_client.get("/api/frp/provision/srv-sync/config", headers=key)
        assert toml.status_code == 200, toml.text
        assert "[[proxies]]" not in toml.text
        res = test_client.get("/api/frp/provision/srv-sync/config-hash", headers=key)
        assert res.status_code == 200, res.text
        assert res.json()["hash"] is not None
        assert res.json() == {"hash": hashlib.sha256(toml.content).hexdigest()}

    def test_a_config_with_a_tunnel_hashes_the_served_toml(self, test_client, db_session):
        _server(db_session)
        cfg = _frp_config(db_session)
        db_session.add(
            FrpTunnel(
                id="t-sync",
                server_id="srv-sync",
                frp_config_id=cfg.id,
                name="sync-ssh",
                tunnel_type="stcp",
                protocol="ssh",
                local_port=22,
                secret_key="sync-stcp-secret",
                visitor_port=6100,
                enabled=True,
            )
        )
        db_session.commit()
        key = _agent_key(db_session, "srv-sync")
        toml = test_client.get("/api/frp/provision/srv-sync/config", headers=key)
        assert toml.status_code == 200, toml.text
        assert "[[proxies]]" in toml.text
        res = test_client.get("/api/frp/provision/srv-sync/config-hash", headers=key)
        assert res.status_code == 200, res.text
        assert res.json() == {"hash": hashlib.sha256(toml.content).hexdigest()}

    def test_an_unknown_server_stays_404_without_an_frp_config(
        self, test_client, db_session, admin_user
    ):
        # An admin JWT is not bound to a server, so the request reaches the lookup.
        res = test_client.get(
            "/api/frp/provision/srv-missing/config-hash", headers=_admin_jwt(test_client)
        )
        assert res.status_code == 404, res.text
        assert res.json()["detail"] == "Server nicht gefunden"

    def test_a_foreign_server_stays_403_without_an_frp_config(self, test_client, db_session):
        _server(db_session, "srv-a", "server-a")
        _server(db_session, "srv-b", "server-b")
        key_a = _agent_key(db_session, "srv-a")
        res = test_client.get("/api/frp/provision/srv-b/config-hash", headers=key_a)
        assert res.status_code == 403, res.text


def _config() -> FrpServerConfig:
    """An unattached ORM instance; the generator only reads attributes."""
    return FrpServerConfig(
        name="frps",
        server_addr="frps.example.test",
        bind_port=7000,
        auth_token="0123456789abcdef",
    )


def _tunnel(name: str, tunnel_type: str = "stcp", **kw) -> FrpTunnel:
    fields = dict(
        name=name,
        tunnel_type=tunnel_type,
        protocol="ssh" if tunnel_type == "stcp" else "web",
        local_ip="127.0.0.1",
        local_port=22 if tunnel_type == "stcp" else 443,
        secret_key="stcp-secret-0123" if tunnel_type == "stcp" else None,
        custom_domains="host.example.test" if tunnel_type == "https" else None,
        enabled=True,
        extra_config=None,
    )
    fields.update(kw)
    return FrpTunnel(**fields)


def _three_tunnels() -> list[FrpTunnel]:
    return [
        _tunnel("three-ssh"),
        _tunnel("three-web", "https"),
        _tunnel("three-rdp", local_port=3389, extra_config='{"transport.useEncryption": true}'),
    ]


@pytest.mark.parametrize(
    "make_tunnels",
    [
        pytest.param(list, id="no-tunnel"),
        pytest.param(lambda: [_tunnel("off-ssh", enabled=False)], id="disabled"),
        pytest.param(lambda: [_tunnel("bare-ssh", secret_key=None)], id="stcp-without-secret"),
    ],
)
def test_frpc_toml_without_an_active_tunnel_has_no_proxies_line(make_tunnels):
    text = generate_frpc_toml(_config(), make_tunnels(), "host", allow_users=["admin"])
    assert "[[proxies]]" not in text.splitlines()
    assert "proxies" not in tomllib.loads(text)


@pytest.mark.parametrize(
    "make_tunnels",
    [
        pytest.param(list, id="no-tunnel"),
        pytest.param(lambda: [_tunnel("one-ssh")], id="one-tunnel"),
        pytest.param(_three_tunnels, id="three-tunnels"),
    ],
)
def test_frpc_toml_leaves_login_fail_exit_and_web_server_to_the_agent(make_tunnels):
    text = generate_frpc_toml(_config(), make_tunnels(), "host", allow_users=["admin"])
    assert "loginFailExit" not in text
    assert "webServer" not in text
    parsed = tomllib.loads(text)
    assert "loginFailExit" not in parsed
    assert "webServer" not in parsed


@pytest.mark.parametrize(
    "make_tunnels",
    [
        pytest.param(lambda: [_tunnel("one-ssh")], id="one-tunnel"),
        pytest.param(_three_tunnels, id="three-tunnels"),
    ],
)
def test_frpc_toml_keeps_every_common_key_before_the_first_proxy(make_tunnels):
    tunnels = make_tunnels()
    text = generate_frpc_toml(_config(), tunnels, "host", allow_users=["admin"])
    lines = text.splitlines()
    first = lines.index("[[proxies]]")
    head = tomllib.loads("\n".join(lines[:first]))
    tail = tomllib.loads("\n".join(lines[first:]))
    full = tomllib.loads(text)
    # Every common key stands ahead of the first [[proxies]] ...
    assert head == {k: v for k, v in full.items() if k != "proxies"}
    # ... after it come proxy tables only ...
    assert tail == {"proxies": full["proxies"]}
    assert len(full["proxies"]) == len(tunnels)
    # ... and no proxy key slipped in front of them.
    assert not _PROXY_KEYS & head.keys()
