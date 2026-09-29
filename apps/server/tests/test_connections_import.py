# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Connections import/export (6.11). The replace-mode import is destructive — it deletes every
existing connection — so the all-or-nothing validation is load-bearing: an invalid entry must reject
the whole import (422) BEFORE the delete, or a bad payload would wipe the table and import nothing."""

import pytest

from app.modules.connections.models import Connection


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_replace_import_with_invalid_entry_wipes_nothing(test_client, db_session, admin_user):
    db_session.add(Connection(id="keep", name="keep", kind="ssh"))
    db_session.commit()
    h = _login(test_client, "admin", "adminpass")

    r = test_client.post(
        "/api/connections/import",
        json={"mode": "replace", "connections": [{"name": "x", "kind": "vnc"}]},  # vnc is invalid
        headers=h,
    )
    assert r.status_code == 422, r.text
    # all-or-nothing: the existing connection must survive a rejected replace import.
    assert db_session.query(Connection).count() == 1
    assert db_session.query(Connection).first().id == "keep"


def test_merge_import_appends_valid_entries(test_client, db_session, admin_user):
    db_session.add(Connection(id="keep", name="keep", kind="ssh"))
    db_session.commit()
    h = _login(test_client, "admin", "adminpass")

    r = test_client.post(
        "/api/connections/import",
        json={"mode": "merge", "connections": [{"name": "new", "kind": "rdp", "host": "h"}]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert {c.name for c in db_session.query(Connection).all()} == {"keep", "new"}


def test_replace_import_replaces_all(test_client, db_session, admin_user):
    db_session.add(Connection(id="old", name="old", kind="ssh"))
    db_session.commit()
    h = _login(test_client, "admin", "adminpass")

    r = test_client.post(
        "/api/connections/import",
        json={
            "mode": "replace",
            "connections": [{"name": "fresh", "kind": "web", "url": "https://x"}],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert {c.name for c in db_session.query(Connection).all()} == {"fresh"}  # old is gone


def test_export_roundtrips_through_import(test_client, db_session, admin_user):
    db_session.add(Connection(id="c1", name="conn1", kind="ssh", host="host1"))
    db_session.commit()
    h = _login(test_client, "admin", "adminpass")

    exported = test_client.get("/api/connections/export", headers=h)
    assert exported.status_code == 200, exported.text
    data = exported.json()
    assert any(c["name"] == "conn1" for c in data)

    # Re-importing the exported payload as a replace must keep the connection (the export shape is
    # importable — otherwise export/import is a broken pair).
    r = test_client.post(
        "/api/connections/import", json={"mode": "replace", "connections": data}, headers=h
    )
    assert r.status_code == 200, r.text
    assert "conn1" in {c.name for c in db_session.query(Connection).all()}


def test_import_checks_server_ids_with_one_query(test_client, db_session, admin_user):
    """R-0068: the import resolves every serverId with ONE query, not one per entry."""
    from sqlalchemy import event

    from app.modules.servers.models import Server

    n = 20
    db_session.add_all(
        [Server(id=f"srv-{i}", name=f"s{i}", hostname=f"s{i}.example") for i in range(n)]
    )
    db_session.commit()
    h = _login(test_client, "admin", "adminpass")
    body = {
        "mode": "merge",
        "connections": [{"name": f"c{i}", "kind": "ssh", "serverId": f"srv-{i}"} for i in range(n)],
    }

    statements = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", _record)
    try:
        r = test_client.post("/api/connections/import", json=body, headers=h)
    finally:
        event.remove(connection, "before_cursor_execute", _record)

    assert r.status_code == 200, r.text
    assert r.json()["imported"] == n
    on_servers = [s for s in statements if "FROM servers" in s]
    assert len(on_servers) == 1, on_servers


@pytest.mark.parametrize(
    "entries",
    [
        # entry 1 fails validation, entry 3 names an unknown server
        {
            1: {"name": "bad", "kind": "vnc"},
            3: {"name": "orphan", "kind": "ssh", "serverId": "nope"},
        },
        # the other way round: the server miss comes first
        {
            1: {"name": "orphan", "kind": "ssh", "serverId": "nope"},
            3: {"name": "bad", "kind": "vnc"},
        },
    ],
)
def test_import_rejects_mixed_errors_in_index_order(test_client, db_session, admin_user, entries):
    """Validation and server errors mixed: `rejected` stays sorted by index, and nothing is written."""
    h = _login(test_client, "admin", "adminpass")
    connections = [entries.get(i, {"name": f"ok{i}", "kind": "ssh"}) for i in range(5)]

    r = test_client.post(
        "/api/connections/import", json={"mode": "merge", "connections": connections}, headers=h
    )

    assert r.status_code == 422, r.text
    assert [e["index"] for e in r.json()["detail"]["rejected"]] == [1, 3]
    assert db_session.query(Connection).count() == 0
