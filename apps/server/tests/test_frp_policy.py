# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The policy file of frps' plugin (frp/policy.py): the server writes the same file the Go
plugin's fixture holds, leaves out what the plugin could not read, writes it after each
change of tunnels, the FRP config or servers, at startup and every SYNC_INTERVAL seconds,
and a failure to write never fails the request that changed the DB."""

import asyncio
import contextlib
import json
import logging
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

import app.core.events as events
import app.main as m
from app.core import config as app_config
from app.core import database
from app.modules.frp import docker_manager, policy
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.proxy_key import proxy_key
from app.modules.monitoring_proxy import router as monitoring_proxy
from app.modules.notifications import stream_hub
from app.modules.servers import router as servers_router
from app.modules.servers.models import Server

# The IDs and SECRET_KEY placeholder of the plugin's fixture (frpspolicy/policy_test.go).
SERVER_A = "0f1e2d3c-4b5a-4968-8776-655443322110"
SERVER_B = "7a0e4d2c-1b3f-4a5e-8c6d-9e0f1a2b3c4d"
FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "agent"
    / "internal"
    / "frpspolicy"
    / "testdata"
    / "policy.json"
)


@pytest.fixture(autouse=True)
def _policy_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "SECRET_KEY", "secret-key-placeholder")
    monkeypatch.setattr(docker_manager, "FRP_CONFIG_DIR", tmp_path)
    return tmp_path / docker_manager.POLICY_FILE


def _login(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _tunnel(tunnel_id: str, server_id: str, tunnel_type: str = "stcp", **over) -> FrpTunnel:
    fields = {
        "id": tunnel_id,
        "server_id": server_id,
        "frp_config_id": "cfg-1",
        "name": tunnel_id,
        "tunnel_type": tunnel_type,
        "protocol": "ssh" if tunnel_type == "stcp" else "web",
        "local_port": 22 if tunnel_type == "stcp" else 443,
        "secret_key": "tunnel-secret-placeholder" if tunnel_type == "stcp" else None,
        "enabled": True,
    }
    fields.update(over)
    return FrpTunnel(**fields)


def _seed(db) -> None:
    db.add(
        FrpServerConfig(
            id="cfg-1",
            name="Default",
            server_addr="frps.example.net",
            bind_port=7000,
            auth_token="frps-token-placeholder",
        )
    )
    db.add(Server(id=SERVER_A, name="server-a"))
    db.add(Server(id=SERVER_B, name="server-b"))
    db.flush()
    db.add_all(
        [
            _tunnel(
                "t-lb",
                SERVER_A,
                "https",
                custom_domains="lb.example",
                extra_config=json.dumps(
                    {
                        "subdomain": "lb",
                        "loadBalancer.group": "web",
                        "loadBalancer.groupKey": "group-key-placeholder",
                    }
                ),
            ),
            _tunnel("t-ssh", SERVER_A),
            _tunnel("t-web", SERVER_A, "https", custom_domains="web.example,www.web.example"),
            _tunnel("t-db", SERVER_B),
        ]
    )
    db.commit()


def _policy(path: Path) -> dict:
    return json.loads(path.read_text())


def test_policy_matches_the_plugin_fixture(db_session):
    # The plugin's tests parse and decide on this file: the server must write exactly it.
    _seed(db_session)
    assert policy.policy_text(db_session) == FIXTURE.read_text()


def test_policy_leaves_out_what_the_plugin_cannot_read(db_session, caplog):
    _seed(db_session)
    db_session.add(Server(id="srv-skipped", name="skipped"))
    db_session.flush()
    db_session.add_all(
        [
            _tunnel("t-no-secret", SERVER_A, secret_key=None),
            _tunnel("t-disabled", SERVER_A, enabled=False),
            _tunnel("t-port", SERVER_A, local_port=0),
            _tunnel("t-plugin", SERVER_A, extra_config=json.dumps({"plugin.type": "http_proxy"})),
            # The API takes an int for any extra_config key; frpc reads subdomain as a string.
            _tunnel(
                "t-int-subdomain", SERVER_A, "https", extra_config=json.dumps({"subdomain": 5})
            ),
            _tunnel("t-only", "srv-skipped", secret_key=None),
        ]
    )
    db_session.commit()

    with caplog.at_level(logging.WARNING, logger="app.modules.frp"):
        servers = policy.build_policy(db_session)["servers"]

    assert sorted(servers) == [SERVER_A, SERVER_B]
    assert sorted(servers[SERVER_A]["proxies"]) == ["t-lb", "t-ssh", "t-web"]
    assert "'t-int-subdomain'" in caplog.text


def test_server_id_with_a_dot_is_left_out(db_session, caplog):
    _seed(db_session)
    db_session.add(Server(id="srv.dot", name="dotted"))
    db_session.flush()
    db_session.add(_tunnel("t-dot", "srv.dot"))
    db_session.commit()

    with caplog.at_level(logging.WARNING, logger="app.modules.frp"):
        servers = policy.build_policy(db_session)["servers"]

    assert sorted(servers) == [SERVER_A, SERVER_B]
    assert "'srv.dot'" in caplog.text


def test_without_frp_config_the_policy_admits_nothing(db_session):
    assert policy.build_policy(db_session) == {"servers": {}, "version": 2}


def test_policy_file_is_0644_without_any_key(db_session, _policy_dir):
    _seed(db_session)
    policy.sync_policy(db_session)

    text = _policy_dir.read_text()
    assert text == FIXTURE.read_text()
    assert stat.S_IMODE(os.lstat(_policy_dir).st_mode) == 0o644
    assert proxy_key(SERVER_A) not in text and proxy_key(SERVER_B) not in text
    assert "tunnel-secret-placeholder" not in text and "frps-token-placeholder" not in text


def test_same_policy_is_not_written_again(_policy_dir):
    text = json.dumps({"servers": {}, "version": 1}) + "\n"
    assert docker_manager.write_frps_policy(text) is True
    inode = os.lstat(_policy_dir).st_ino

    assert docker_manager.write_frps_policy(text) is False
    assert os.lstat(_policy_dir).st_ino == inode

    # A changed mode, a changed content and a symlink are each put right.
    os.chmod(_policy_dir, 0o600)
    assert docker_manager.write_frps_policy(text) is True
    assert stat.S_IMODE(os.lstat(_policy_dir).st_mode) == 0o644
    _policy_dir.write_text(text.replace("1", "2"))
    assert docker_manager.write_frps_policy(text) is True
    assert _policy_dir.read_text() == text
    target = _policy_dir.with_name("elsewhere.json")
    target.write_text(text)
    os.chmod(target, 0o644)
    _policy_dir.unlink()
    _policy_dir.symlink_to(target)
    assert docker_manager.write_frps_policy(text) is True
    assert stat.S_ISREG(os.lstat(_policy_dir).st_mode)


def test_tunnel_routes_write_the_policy(test_client, db_session, admin_user, _policy_dir):
    _seed(db_session)
    h = _login(test_client)
    body = {
        "server_id": SERVER_B,
        "frp_config_id": "cfg-1",
        "name": "web-b",
        "tunnel_type": "https",
        "protocol": "web",
        "local_port": 8443,
        "custom_domains": "b.example",
    }

    created = test_client.post("/api/frp/tunnels", json=body, headers=h)
    assert created.status_code == 201, created.text
    tunnel_id = created.json()["id"]
    proxies = _policy(_policy_dir)["servers"][SERVER_B]["proxies"]
    assert proxies[tunnel_id]["customDomains"] == ["b.example"]

    updated = test_client.put(
        f"/api/frp/tunnels/{tunnel_id}", json={"custom_domains": "c.example"}, headers=h
    )
    assert updated.status_code == 200, updated.text
    proxies = _policy(_policy_dir)["servers"][SERVER_B]["proxies"]
    assert proxies[tunnel_id]["customDomains"] == ["c.example"]

    deleted = test_client.delete(f"/api/frp/tunnels/{tunnel_id}", headers=h)
    assert deleted.status_code == 204, deleted.text
    assert sorted(_policy(_policy_dir)["servers"][SERVER_B]["proxies"]) == ["t-db"]


def test_config_routes_write_the_policy(test_client, db_session, admin_user, _policy_dir):
    _seed(db_session)
    h = _login(test_client)

    r = test_client.put("/api/frp/server-config/cfg-1", json={"name": "Renamed"}, headers=h)
    assert r.status_code == 200, r.text
    # The admin of the login has access to every server, so it stands in allowUsers.
    expected = FIXTURE.read_text().replace('"ops-admin"', '"admin"')
    assert _policy_dir.read_text() == expected

    # Without the route, so the file still holds the tunnels: only the delete's own write
    # empties it.
    db_session.query(FrpTunnel).delete()
    db_session.commit()
    r = test_client.delete("/api/frp/server-config/cfg-1", headers=h)
    assert r.status_code == 204, r.text
    assert _policy(_policy_dir) == {"servers": {}, "version": 2}


def _allow_users(path: Path, server_id: str, tunnel_id: str) -> list[str]:
    return _policy(path)["servers"][server_id]["proxies"][tunnel_id]["allowUsers"]


def test_user_routes_write_the_policy(test_client, db_session, admin_user, _policy_dir):
    # allowUsers holds the admins and the users assigned to the server (get_allow_users).
    _seed(db_session)
    h = _login(test_client)
    body = {"username": "viewer", "password": "viewerpass1", "server_ids": [SERVER_B]}

    created = test_client.post("/api/users", json=body, headers=h)
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    assert _allow_users(_policy_dir, SERVER_A, "t-ssh") == ["admin"]
    assert _allow_users(_policy_dir, SERVER_B, "t-db") == ["admin", "viewer"]

    moved = test_client.put(f"/api/users/{user_id}", json={"server_ids": [SERVER_A]}, headers=h)
    assert moved.status_code == 200, moved.text
    assert _allow_users(_policy_dir, SERVER_A, "t-ssh") == ["admin", "viewer"]
    assert _allow_users(_policy_dir, SERVER_B, "t-db") == ["admin"]

    promoted = test_client.put(
        f"/api/users/{user_id}", json={"is_admin": True, "server_ids": []}, headers=h
    )
    assert promoted.status_code == 200, promoted.text
    assert _allow_users(_policy_dir, SERVER_B, "t-db") == ["admin", "viewer"]

    deleted = test_client.delete(f"/api/users/{user_id}", headers=h)
    assert deleted.status_code == 204, deleted.text
    assert _allow_users(_policy_dir, SERVER_A, "t-ssh") == ["admin"]
    assert _allow_users(_policy_dir, SERVER_B, "t-db") == ["admin"]
    # An https proxy has no allowed users and no secret key.
    web = _policy(_policy_dir)["servers"][SERVER_A]["proxies"]["t-web"]
    assert (web["allowUsers"], web["skHash"]) == ([], "")


def test_server_delete_writes_the_policy(
    test_client, db_session, admin_user, _policy_dir, monkeypatch
):
    _seed(db_session)
    policy.sync_policy(db_session)
    monkeypatch.setattr(
        servers_router.httpx, "delete", lambda *a, **k: SimpleNamespace(status_code=204)
    )

    r = test_client.delete(f"/api/servers/{SERVER_B}", headers=_login(test_client))

    assert r.status_code == 204, r.text
    assert sorted(_policy(_policy_dir)["servers"]) == [SERVER_A]


def test_failed_write_keeps_the_request_and_logs_the_type_alone(
    test_client, db_session, admin_user, monkeypatch, caplog
):
    _seed(db_session)
    h = _login(test_client)

    def _refuse(_text):
        raise PermissionError("postgresql://user:db-password-placeholder@db/adminhelper")

    monkeypatch.setattr(policy, "write_frps_policy", _refuse)
    with caplog.at_level(logging.ERROR, logger="app.modules.frp.policy"):
        r = test_client.delete("/api/frp/tunnels/t-ssh", headers=h)

    assert r.status_code == 204, r.text
    assert db_session.get(FrpTunnel, "t-ssh") is None
    assert "frps policy not written (PermissionError)" in caplog.text
    assert "db-password-placeholder" not in caplog.text


def _own_sessions(db_session):
    # Sessions on the test's connection: they see its rows and leave its transaction alone.
    return sessionmaker(bind=db_session.connection(), autoflush=False)


async def _until(condition, rounds: int = 500) -> bool:
    for _ in range(rounds):
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


def test_periodic_sync_puts_back_a_removed_or_changed_file(
    db_session, monkeypatch, caplog, _policy_dir
):
    _seed(db_session)
    sessions = _own_sessions(db_session)
    calls = []

    def _session():
        calls.append(None)
        if len(calls) == 1:
            raise RuntimeError("postgresql://user:db-password-placeholder@db/adminhelper")
        return sessions()

    monkeypatch.setattr(policy, "SYNC_INTERVAL", 0)
    monkeypatch.setattr(database, "SessionLocal", _session)
    expected = FIXTURE.read_text()

    async def _run():
        task = asyncio.create_task(policy.keep_policy_current())
        try:
            # The first round fails; the loop goes on and writes the file.
            assert await _until(lambda: _policy_dir.exists())
            _policy_dir.write_text("{}\n")
            assert await _until(lambda: _policy_dir.read_text() == expected)
            _policy_dir.unlink()
            assert await _until(lambda: _policy_dir.exists())
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    with caplog.at_level(logging.ERROR, logger="app.modules.frp.policy"):
        asyncio.run(_run())

    assert _policy_dir.read_text() == expected
    assert "frps policy sync failed (RuntimeError)" in caplog.text
    assert "db-password-placeholder" not in caplog.text


def test_startup_writes_the_policy(db_session, monkeypatch, _policy_dir):
    _seed(db_session)
    monkeypatch.setattr(m, "SessionLocal", _own_sessions(db_session))
    for step in ("_ensure_admin", "_check_frps_server_configs", "_ensure_frps_config"):
        monkeypatch.setattr(m, step, lambda _db: None)

    m._run_startup_tasks()

    assert _policy_dir.read_text() == FIXTURE.read_text()


def test_lifespan_starts_and_cancels_the_periodic_sync(test_client, monkeypatch):
    seen = []

    async def _keep():
        seen.append("started")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            seen.append("cancelled")
            raise

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(m, "_run_startup_tasks", lambda: None)
    monkeypatch.setattr(m.frp_policy, "keep_policy_current", _keep)
    monkeypatch.setattr(events, "fire_event", lambda *a, **k: None)
    monkeypatch.setattr(stream_hub, "start", _noop)
    monkeypatch.setattr(stream_hub, "stop", _noop)
    monkeypatch.setattr(monitoring_proxy, "_client", httpx.AsyncClient(timeout=30))

    with test_client:
        pass

    assert seen == ["started", "cancelled"]
