# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""POST /api/servers/{id}/frp-key/rotate (R-1316): an admin replaces one server's frps
proxy key. The generation rises, the policy holds the new key's hash, every frpc.toml the
server hands out (sync, its hash, single and bulk download) carries the new key, the other
servers keep theirs, and the rotation lands one audit row."""

import io
import json
import secrets
import zipfile

import pytest

from app.core.auth import hash_api_key
from app.modules.api_keys.models import ApiKey
from app.modules.audit.models import AuditLog
from app.modules.frp import docker_manager, policy
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.proxy_key import proxy_key, proxy_key_hash
from app.modules.servers.models import Server

SERVER_A = "srv-rot-a"
SERVER_B = "srv-rot-b"


@pytest.fixture(autouse=True)
def policy_file(tmp_path, monkeypatch):
    monkeypatch.setattr(docker_manager, "FRP_CONFIG_DIR", tmp_path)
    return tmp_path / docker_manager.POLICY_FILE


def _login(client, username="admin", password="adminpass") -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed(db) -> dict[str, str]:
    """Two servers with one active tunnel each; returns the agent key of SERVER_A."""
    db.add(
        FrpServerConfig(
            id="cfg-rot",
            name="Default",
            server_addr="frps.example.test",
            bind_port=7000,
            auth_token="rot-frps-auth-token",
        )
    )
    for sid in (SERVER_A, SERVER_B):
        db.add(Server(id=sid, name=f"{sid}-name"))
    db.flush()
    for sid in (SERVER_A, SERVER_B):
        db.add(
            FrpTunnel(
                id=f"t-{sid}",
                server_id=sid,
                frp_config_id="cfg-rot",
                name="ssh",
                tunnel_type="stcp",
                protocol="ssh",
                local_port=22,
                secret_key=f"{sid}-stcp-secret",
                enabled=True,
            )
        )
    raw = f"adminhelper_{secrets.token_urlsafe(16)}"
    db.add(
        ApiKey(
            name=f"agent-{SERVER_A}",
            hashed_key=hash_api_key(raw),
            permission="read",
            server_id=SERVER_A,
        )
    )
    db.commit()
    return {"X-API-Key": raw}


def _hash_of(client, agent: dict[str, str]) -> str:
    r = client.get(f"/api/frp/provision/{SERVER_A}/config-hash", headers=agent)
    assert r.status_code == 200, r.text
    return r.json()["hash"]


def test_a_rotation_replaces_the_key_of_its_server_everywhere(
    test_client, db_session, admin_user, policy_file
):
    agent = _seed(db_session)
    admin = _login(test_client)
    hash_before = _hash_of(test_client, agent)

    first = test_client.post(f"/api/servers/{SERVER_A}/frp-key/rotate", headers=admin)
    second = test_client.post(f"/api/servers/{SERVER_A}/frp-key/rotate", headers=admin)

    assert first.status_code == 200, first.text
    assert (first.json(), second.json()) == (
        {"generation": 1, "policySynced": True},
        {"generation": 2, "policySynced": True},
    )
    db_session.expire_all()
    assert db_session.get(Server, SERVER_A).frp_key_generation == 2
    assert db_session.get(Server, SERVER_B).frp_key_generation == 0

    servers = json.loads(policy_file.read_text())["servers"]
    assert servers[SERVER_A]["keyHash"] == proxy_key_hash(SERVER_A, 2)
    assert servers[SERVER_B]["keyHash"] == proxy_key_hash(SERVER_B, 0)

    synced = test_client.get(f"/api/frp/provision/{SERVER_A}/config", headers=agent)
    assert synced.status_code == 200, synced.text
    assert proxy_key(SERVER_A, 2) in synced.text
    assert proxy_key(SERVER_A, 0) not in synced.text
    assert _hash_of(test_client, agent) != hash_before

    single = test_client.get(f"/api/frp/generate/frpc-toml/{SERVER_A}", headers=admin)
    assert single.status_code == 200, single.text
    assert single.text == synced.text

    bulk = test_client.get("/api/frp/generate/bulk-zip", headers=admin)
    assert bulk.status_code == 200, bulk.text
    with zipfile.ZipFile(io.BytesIO(bulk.content)) as zf:
        assert zf.read(f"clients/{SERVER_A}-name/frpc.toml").decode() == synced.text
        assert proxy_key(SERVER_B, 0) in zf.read(f"clients/{SERVER_B}-name/frpc.toml").decode()


def test_a_rotation_is_audited_with_the_new_generation(test_client, db_session, admin_user):
    _seed(db_session)
    r = test_client.post(f"/api/servers/{SERVER_A}/frp-key/rotate", headers=_login(test_client))
    assert r.status_code == 200, r.text

    rows = db_session.query(AuditLog).filter(AuditLog.action == "server.frp_key.rotated").all()
    assert len(rows) == 1
    row = rows[0]
    assert (row.actor_type, row.actor_label) == ("user", "admin")
    assert (row.object_type, row.object_id, row.object_label) == (
        "server",
        SERVER_A,
        f"{SERVER_A}-name",
    )
    assert (row.detail, row.status) == ("generation=1", "success")
    assert proxy_key(SERVER_A, 1) not in " ".join(str(v) for v in vars(row).values())


def test_an_unknown_server_is_404_and_not_audited(test_client, db_session, admin_user):
    r = test_client.post("/api/servers/does-not-exist/frp-key/rotate", headers=_login(test_client))
    assert r.status_code == 404, r.text
    assert (
        db_session.query(AuditLog).filter(AuditLog.action == "server.frp_key.rotated").count() == 0
    )


def test_a_non_admin_cannot_rotate(test_client, db_session, normal_user):
    _seed(db_session)
    viewer = _login(test_client, "viewer", "viewerpass")
    # 403 from the authz dependency, also for an id that does not exist.
    for sid in (SERVER_A, "does-not-exist"):
        r = test_client.post(f"/api/servers/{sid}/frp-key/rotate", headers=viewer)
        assert r.status_code == 403, r.text
    db_session.expire_all()
    assert db_session.get(Server, SERVER_A).frp_key_generation == 0


def test_without_a_login_the_rotation_is_401(test_client, db_session):
    _seed(db_session)
    r = test_client.post(f"/api/servers/{SERVER_A}/frp-key/rotate")
    assert r.status_code == 401, r.text


def test_a_rotation_whose_policy_write_fails_stands_and_says_so(
    test_client, db_session, admin_user, policy_file, monkeypatch
):
    """R-1437: the policy is best effort; a failed write leaves the rotation in place
    (generation committed, audited) and the answer tells the admin frps lags behind."""
    _seed(db_session)

    def refuse(_text: str) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(policy, "write_frps_policy", refuse)
    r = test_client.post(f"/api/servers/{SERVER_A}/frp-key/rotate", headers=_login(test_client))

    assert r.status_code == 200, r.text
    assert r.json() == {"generation": 1, "policySynced": False}
    db_session.expire_all()
    assert db_session.get(Server, SERVER_A).frp_key_generation == 1
    assert not policy_file.exists()
    rows = db_session.query(AuditLog).filter(AuditLog.action == "server.frp_key.rotated").all()
    assert [row.detail for row in rows] == ["generation=1"]
