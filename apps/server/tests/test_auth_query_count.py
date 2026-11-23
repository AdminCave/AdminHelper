# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-0692: authenticating a user with assigned servers does not load those servers, their
connections and their tunnels; the user list loads the servers of all users at once."""

import re
from contextlib import contextmanager

from sqlalchemy import event

from app.core.auth import hash_password
from app.modules.connections.models import Connection
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.servers.models import Server
from app.modules.users.models import User

_TABLES = ("servers", "connections", "frp_tunnels")


@contextmanager
def _statements(db_session):
    seen: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(connection, "before_cursor_execute", _record)


def _from(statements: list[str], table: str) -> list[str]:
    pattern = re.compile(rf"\bFROM {table}\b|\bJOIN {table}\b")
    return [s for s in statements if pattern.search(s)]


def _user_with_server(db_session, n: int) -> None:
    server = Server(id=f"srv-{n}", name=f"s{n}", hostname=f"s{n}.example.test")
    db_session.add(server)
    db_session.add(
        Connection(id=f"c-{n}", name="ssh", kind="ssh", host="h", port=22, server_id=server.id)
    )
    db_session.add(
        FrpTunnel(
            id=f"t-{n}",
            server_id=server.id,
            frp_config_id="cfg-1",
            name=f"tun-{n}",
            tunnel_type="stcp",
            protocol="ssh",
            local_port=22,
            secret_key="s",
            visitor_port=6000 + n,
            enabled=True,
        )
    )
    db_session.add(
        User(
            username=f"user{n}",
            hashed_password=hash_password("userpass"),
            is_admin=False,
            servers=[server],
        )
    )


def _seed(db_session, users: int) -> None:
    db_session.add(
        FrpServerConfig(
            id="cfg-1",
            name="Default",
            server_addr="frps.example.net",
            bind_port=7000,
            auth_token="frps-auth",
        )
    )
    for n in range(users):
        _user_with_server(db_session, n)
    db_session.commit()


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_authentication_does_not_load_the_users_servers(test_client, db_session):
    _seed(db_session, 1)
    headers = _login(test_client, "user0", "userpass")
    # A fresh identity map, as in a new request: nothing the login loaded is reused.
    db_session.expunge_all()
    with _statements(db_session) as seen:
        r = test_client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    assert {t: _from(seen, t) for t in _TABLES} == {t: [] for t in _TABLES}


def test_the_user_list_loads_all_servers_in_one_query(test_client, db_session, admin_user):
    _seed(db_session, 3)
    headers = _login(test_client, "admin", "adminpass")
    db_session.expunge_all()
    with _statements(db_session) as seen:
        r = test_client.get("/api/users", headers=headers)
    assert r.status_code == 200, r.text
    assert sorted(u["server_ids"] for u in r.json() if u["username"] != "admin") == [
        ["srv-0"],
        ["srv-1"],
        ["srv-2"],
    ]
    assert len(_from(seen, "servers")) == 1, _from(seen, "servers")
