# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1699, R-1737: the frps policy and the bulk ZIP ask for the allowed users of all
servers at once, so their statement count does not grow with the number of servers."""

import io
import zipfile
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from app.core import config as app_config
from app.core.auth import hash_password
from app.modules.frp import docker_manager, policy
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.servers.models import Server
from app.modules.users.models import User


@pytest.fixture(autouse=True)
def _policy_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "SECRET_KEY", "secret-key-placeholder")
    monkeypatch.setattr(docker_manager, "FRP_CONFIG_DIR", tmp_path)


@contextmanager
def _statements(db_session):
    # Both measurements start from the same state: a commit in between expires what the
    # test session holds, and reloading it would count as a statement of the second.
    db_session.expire_all()
    seen: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(connection, "before_cursor_execute", _record)


def _config(db) -> None:
    db.add(
        FrpServerConfig(
            id="cfg-1",
            name="Default",
            server_addr="frps.example.net",
            bind_port=7000,
            auth_token="frps-token-placeholder",
        )
    )
    db.flush()


def _users(db) -> list[User]:
    users = [
        User(username=name, hashed_password=hash_password("pw"), is_admin=name == "admin")
        for name in ("admin", "alice", "bob")
    ]
    db.add_all(users)
    db.flush()
    return users


def _servers(db, users: list[User], first: int, count: int) -> None:
    for n in range(first, first + count):
        server = Server(id=f"srv-{n}", name=f"server-{n}")
        db.add(server)
        db.flush()
        db.add(
            FrpTunnel(
                id=f"t-{n}",
                server_id=server.id,
                frp_config_id="cfg-1",
                name=f"tun-{n}",
                tunnel_type="stcp",
                protocol="ssh",
                local_port=22,
                secret_key="tunnel-secret-placeholder",
                visitor_port=6000 + n,
                enabled=True,
            )
        )
        for user in users[1 : 1 + n % 3]:
            user.servers.append(server)
    db.commit()


def _sync_count(db_session) -> int:
    with _statements(db_session) as seen:
        assert policy.sync_policy(db_session)
    return len(seen)


def test_the_policy_sync_does_not_query_per_server(db_session):
    _config(db_session)
    users = _users(db_session)
    _servers(db_session, users, 1, 1)
    one = _sync_count(db_session)

    _servers(db_session, users, 2, 4)
    five = _sync_count(db_session)

    assert len(policy.build_policy(db_session)["servers"]) == 5
    assert five == one


def test_the_policy_keeps_the_allowed_users_of_each_server(db_session):
    _config(db_session)
    users = _users(db_session)
    _servers(db_session, users, 1, 3)

    servers = policy.build_policy(db_session)["servers"]

    allowed = {
        sid: entry["proxies"][f"t-{sid[4:]}"]["allowUsers"] for sid, entry in servers.items()
    }
    assert allowed == {
        "srv-1": ["admin", "alice"],
        "srv-2": ["admin", "alice", "bob"],
        "srv-3": ["admin"],
    }


def _zip_count(test_client, db_session, headers) -> tuple[int, list[str]]:
    with _statements(db_session) as seen:
        r = test_client.get("/api/frp/generate/bulk-zip", headers=headers)
    assert r.status_code == 200, r.text
    return len(seen), zipfile.ZipFile(io.BytesIO(r.content)).namelist()


def test_the_bulk_zip_does_not_query_per_server(test_client, db_session):
    _config(db_session)
    users = _users(db_session)
    _servers(db_session, users, 1, 1)
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    one, _ = _zip_count(test_client, db_session, headers)

    _servers(db_session, users, 2, 4)
    five, names = _zip_count(test_client, db_session, headers)

    assert sum(name.startswith("clients/") for name in names) == 5
    assert {"visitors/alice.toml", "visitors/bob.toml"} <= set(names)
    assert five == one
