# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the agent's frpc sync relies on from the server (R-0398).

`GET /api/frp/provision/{id}/config-hash` answers `{"hash": null}` when no FRP
config exists: the agent reads a 404 as permanent, so a host without FRP would
fail every timer run. A host with a config but without an active tunnel (none the
generator writes as `[[proxies]]`) gets the common part without the frps
credentials and without proxies, and its hash: it needs no frps credentials, and
every agent that applies the text leaves no tunnel up (the current one stops frpc).
The provisioning bundle carries the same text. The 403 of the scope check and the
404 for an unknown server stay.

The agent puts its own top-level keys (`loginFailExit`, `webServer.*`) in front of
the server text and compares the text before the first `[[proxies]]` to choose
between a reload and a restart. Both hold only while the generator writes neither
key and keeps every common key ahead of the first proxy table.
"""

from __future__ import annotations

import hashlib
import itertools
import secrets
import tomllib
from datetime import timedelta

import pytest

from app.core.auth import hash_api_key
from app.modules.api_keys.models import ApiKey
from app.modules.connections.models import Connection
from app.modules.frp.config_generator import active_tunnels, generate_frpc_toml
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


def _add_tunnel(db, cfg: FrpServerConfig, name: str, **kw) -> None:
    """An stcp tunnel of srv-sync under cfg, active unless kw says otherwise."""
    fields = dict(
        id=f"t-{name}",
        server_id="srv-sync",
        frp_config_id=cfg.id,
        name=name,
        tunnel_type="stcp",
        protocol="ssh",
        local_port=22,
        secret_key=f"{name}-stcp-secret",
        enabled=True,
    )
    fields.update(kw)
    db.add(FrpTunnel(**fields))
    db.commit()


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

    @pytest.mark.parametrize(
        "inactive",
        [
            pytest.param([], id="no-tunnel"),
            pytest.param([{"enabled": False}], id="disabled"),
            pytest.param([{"secret_key": None}], id="stcp-without-secret"),
            pytest.param([{"enabled": False}, {"secret_key": None}], id="both"),
        ],
    )
    def test_without_an_active_tunnel_the_config_has_no_tunnel_and_no_frps_credentials(
        self, test_client, db_session, inactive
    ):
        _server(db_session)
        cfg = _frp_config(db_session)
        for i, kw in enumerate(inactive):
            _add_tunnel(db_session, cfg, f"inactive-{i}", **kw)
        key = _agent_key(db_session, "srv-sync")
        toml = test_client.get("/api/frp/provision/srv-sync/config", headers=key)
        assert toml.status_code == 200, toml.text
        assert "[[proxies]]" not in toml.text.splitlines()
        assert "sync-frps-auth-token" not in toml.text
        assert "auth.token" not in toml.text
        assert "stcp-secret" not in toml.text
        parsed = tomllib.loads(toml.text)
        assert "proxies" not in parsed
        assert "token" not in parsed.get("auth", {})
        res = test_client.get("/api/frp/provision/srv-sync/config-hash", headers=key)
        assert res.status_code == 200, res.text
        assert res.json() == {"hash": hashlib.sha256(toml.content).hexdigest()}

    def test_an_active_tunnel_next_to_inactive_ones_is_served_and_hashed(
        self, test_client, db_session
    ):
        _server(db_session)
        cfg = _frp_config(db_session)
        _add_tunnel(db_session, cfg, "off-ssh", enabled=False)
        _add_tunnel(db_session, cfg, "bare-ssh", secret_key=None)
        _add_tunnel(db_session, cfg, "on-ssh")
        key = _agent_key(db_session, "srv-sync")
        toml = test_client.get("/api/frp/provision/srv-sync/config", headers=key)
        assert toml.status_code == 200, toml.text
        assert [p["name"] for p in tomllib.loads(toml.text)["proxies"]] == ["on-ssh"]
        assert 'auth.token = "sync-frps-auth-token"' in toml.text.splitlines()
        res = test_client.get("/api/frp/provision/srv-sync/config-hash", headers=key)
        assert res.status_code == 200, res.text
        assert res.json() == {"hash": hashlib.sha256(toml.content).hexdigest()}

    def test_only_the_tunnels_of_this_server_under_the_chosen_config_are_served(
        self, test_client, db_session
    ):
        _server(db_session)
        _server(db_session, "srv-other", "other-host")
        cfg = _frp_config(db_session)
        # created_at by hand: the server default is the transaction's now(), the
        # same for both rows, and the id tiebreaker would pick cfg-later.
        later = FrpServerConfig(
            id="cfg-later",
            name="Later",
            server_addr="frps-later.example.test",
            bind_port=7000,
            auth_token="later-frps-auth-token",
            created_at=cfg.created_at + timedelta(days=1),
        )
        db_session.add(later)
        db_session.commit()
        _add_tunnel(db_session, cfg, "own-ssh")
        _add_tunnel(db_session, cfg, "foreign-ssh", server_id="srv-other")
        _add_tunnel(db_session, later, "own-later-ssh")
        key = _agent_key(db_session, "srv-sync")
        toml = test_client.get("/api/frp/provision/srv-sync/config", headers=key)
        assert toml.status_code == 200, toml.text
        parsed = tomllib.loads(toml.text)
        assert parsed["serverAddr"] == "frps.example.test"
        assert [p["name"] for p in parsed["proxies"]] == ["own-ssh"]
        res = test_client.get("/api/frp/provision/srv-sync/config-hash", headers=key)
        assert res.status_code == 200, res.text
        assert res.json() == {"hash": hashlib.sha256(toml.content).hexdigest()}

    def test_the_admin_frpc_toml_route_serves_the_sync_text(
        self, test_client, db_session, admin_user
    ):
        # R-0973: GET /generate/frpc-toml/{id} took its config from the first tunnel, so a
        # server with tunnels under two configs got another text than its agent syncs.
        _server(db_session)
        cfg = _frp_config(db_session)
        later = FrpServerConfig(
            id="cfg-later",
            name="Later",
            server_addr="frps-later.example.test",
            bind_port=7000,
            auth_token="later-frps-auth-token",
            created_at=cfg.created_at + timedelta(days=1),
        )
        db_session.add(later)
        db_session.commit()
        _add_tunnel(db_session, cfg, "own-ssh")
        # Sorts first (active_tunnels sorts by name), so the old route took cfg-later.
        _add_tunnel(db_session, later, "a-later-ssh")
        synced = test_client.get(
            "/api/frp/provision/srv-sync/config", headers=_agent_key(db_session, "srv-sync")
        )
        assert synced.status_code == 200, synced.text
        admin = test_client.get(
            "/api/frp/generate/frpc-toml/srv-sync", headers=_admin_jwt(test_client)
        )
        assert admin.status_code == 200, admin.text
        assert admin.text == synced.text
        assert "later-frps-auth-token" not in admin.text

    def test_the_admin_frpc_toml_route_refuses_a_tunnel_only_in_a_later_config(
        self, test_client, db_session, admin_user
    ):
        # The sync takes the earliest config; a tunnel under a later one is not in its
        # text, so the admin route has no tunnel to show either.
        _server(db_session)
        cfg = _frp_config(db_session)
        later = FrpServerConfig(
            id="cfg-later",
            name="Later",
            server_addr="frps-later.example.test",
            bind_port=7000,
            auth_token="later-frps-auth-token",
            created_at=cfg.created_at + timedelta(days=1),
        )
        db_session.add(later)
        db_session.commit()
        _add_tunnel(db_session, later, "a-later-ssh")
        admin = test_client.get(
            "/api/frp/generate/frpc-toml/srv-sync", headers=_admin_jwt(test_client)
        )
        assert admin.status_code == 404, admin.text
        assert "later-frps-auth-token" not in admin.text

    def test_the_hash_stays_when_a_tunnel_row_moves_in_the_table(self, test_client, db_session):
        # connection_id is indexed but not part of the frpc config: updating it is
        # no HOT update, so the new row version lands behind b-rdp and Postgres
        # returns the tunnels in a different order (R-0452).
        _server(db_session)
        cfg = _frp_config(db_session)
        _add_tunnel(db_session, cfg, "a-ssh")
        _add_tunnel(db_session, cfg, "b-rdp", protocol="rdp", local_port=3389)
        key = _agent_key(db_session, "srv-sync")
        before = test_client.get("/api/frp/provision/srv-sync/config-hash", headers=key)
        assert before.status_code == 200, before.text

        db_session.add(Connection(id="conn-a", name="a-ssh", kind="ssh", server_id="srv-sync"))
        db_session.commit()
        db_session.get(FrpTunnel, "t-a-ssh").connection_id = "conn-a"
        db_session.commit()

        after = test_client.get("/api/frp/provision/srv-sync/config-hash", headers=key)
        assert after.status_code == 200, after.text
        assert after.json() == before.json()
        toml = test_client.get("/api/frp/provision/srv-sync/config", headers=key)
        assert toml.status_code == 200, toml.text
        assert after.json() == {"hash": hashlib.sha256(toml.content).hexdigest()}

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
        pytest.param(lambda: [_tunnel("off-ssh", enabled=False)], id="disabled"),
        pytest.param(lambda: [_tunnel("bare-ssh", secret_key=None)], id="stcp-without-secret"),
    ],
)
def test_frpc_toml_without_an_active_tunnel_is_the_common_part_without_the_token(make_tunnels):
    text = generate_frpc_toml(_config(), make_tunnels(), "host", allow_users=["admin"])
    assert "0123456789abcdef" not in text
    assert "stcp-secret-0123" not in text
    assert "auth.token" not in text
    # Everything else of the common part stays as with a tunnel, so the text is
    # still a frpc.toml an agent can write.
    one = generate_frpc_toml(_config(), [_tunnel("one-ssh")], "host", allow_users=["admin"])
    expected = tomllib.loads(one)
    assert expected["auth"].pop("token") == "0123456789abcdef"
    del expected["proxies"]
    assert tomllib.loads(text) == expected


@pytest.mark.parametrize(
    "make_tunnels",
    [
        pytest.param(list, id="no-tunnel"),
        pytest.param(lambda: [_tunnel("off-ssh", enabled=False)], id="disabled"),
        pytest.param(lambda: [_tunnel("bare-ssh", secret_key=None)], id="stcp-without-secret"),
        pytest.param(_three_tunnels, id="three-tunnels"),
        pytest.param(
            lambda: [
                _tunnel("mix-off", enabled=False),
                _tunnel("mix-ssh"),
                _tunnel("mix-bare", secret_key=None),
                _tunnel("mix-web", "https"),
                _tunnel("mix-web-off", "https", enabled=False),
            ],
            id="mixed",
        ),
    ],
)
def test_active_tunnels_are_the_proxies_the_generator_writes(make_tunnels):
    # The generator writes the frps token only when active_tunnels finds a tunnel;
    # it has to pick what the generator writes as proxies.
    tunnels = make_tunnels()
    text = generate_frpc_toml(_config(), tunnels, "host", allow_users=["admin"])
    proxies = tomllib.loads(text).get("proxies", [])
    assert [t.name for t in active_tunnels(tunnels)] == [p["name"] for p in proxies]


def test_frpc_toml_is_the_same_in_every_order_of_the_tunnels():
    # The order the database returns the rows in must not reach the text the
    # config hash covers (R-0452).
    text = generate_frpc_toml(_config(), _three_tunnels(), "host", allow_users=["admin"])
    for order in itertools.permutations(_three_tunnels()):
        assert generate_frpc_toml(_config(), list(order), "host", allow_users=["admin"]) == text
    names = [p["name"] for p in tomllib.loads(text)["proxies"]]
    assert names == sorted(names)


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
