# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Connections import/export (6.11). The replace-mode import is destructive — it deletes every
existing connection — so the all-or-nothing validation is load-bearing: an invalid entry must reject
the whole import (422) BEFORE the delete, or a bad payload would wipe the table and import nothing."""

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
