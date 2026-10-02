# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""save_connections upsert+delete sync (6.145). It is reachable from hook scripts — admin-written code
that relies on the semantics — and replaced the earlier DELETE-ALL+INSERT-ALL. A regression back to
'wipe everything' (or losing the delete-of-missing) would go unnoticed without this."""

from sqlalchemy.orm import sessionmaker

from app.core import database
from app.modules.connections import storage
from app.modules.connections.models import Connection


def _bind_sessionlocal(db_session, monkeypatch):
    # save_connections opens its own SessionLocal; bind a fresh one to the test connection so its
    # commit lands in the test's transaction (same pattern as test_hooks).
    monkeypatch.setattr(
        database, "SessionLocal", sessionmaker(bind=db_session.connection(), autoflush=False)
    )


def test_save_connections_updates_inserts_and_deletes(db_session, monkeypatch):
    _bind_sessionlocal(db_session, monkeypatch)
    db_session.add(Connection(id="keep", name="old-name", kind="ssh"))
    db_session.add(Connection(id="gone", name="to-delete", kind="ssh"))
    db_session.commit()

    # Sync: update "keep", drop "gone" (absent from the list), insert "new".
    storage.save_connections(
        [
            {"id": "keep", "name": "new-name", "kind": "ssh"},
            {"id": "new", "name": "fresh", "kind": "rdp"},
        ]
    )

    rows = {c.id: c for c in db_session.query(Connection).all()}
    assert set(rows) == {"keep", "new"}, "gone must be deleted, new inserted"
    assert rows["keep"].name == "new-name", "existing id is updated in place, not recreated"
    assert rows["new"].kind == "rdp"


def test_save_connections_empty_list_clears_all(db_session, monkeypatch):
    # The delete-of-missing branch taken to its extreme: an empty list removes every row.
    _bind_sessionlocal(db_session, monkeypatch)
    db_session.add(Connection(id="a", name="a", kind="ssh"))
    db_session.commit()

    storage.save_connections([])

    assert db_session.query(Connection).count() == 0


# Only the API fields map to columns; any other key — a column name such as extra_data or
# created_at included — is an extra entry, kept in extra_data and nothing else.


def test_from_dict_keeps_column_names_out_of_their_columns():
    import json

    conn = Connection.from_dict(
        {
            "name": "a",
            "kind": "ssh",
            "keyPath": "/k",
            "trustCert": True,
            "extra_data": '{"host": "other.example"}',
            "created_at": "2000-01-01T00:00:00",
        }
    )
    assert conn.key_path == "/k" and conn.trust_cert is True
    assert conn.created_at is None
    assert json.loads(conn.extra_data) == {
        "extra_data": '{"host": "other.example"}',
        "created_at": "2000-01-01T00:00:00",
    }


def test_update_from_dict_keeps_column_names_out_of_their_columns():
    import json

    conn = Connection(id="c", name="old", kind="ssh")
    conn.update_from_dict({"name": "new", "extra_data": "x", "created_at": "2000-01-01T00:00:00"})
    assert conn.name == "new"
    assert conn.created_at is None
    assert json.loads(conn.extra_data) == {"extra_data": "x", "created_at": "2000-01-01T00:00:00"}


def _admin_headers(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_COLUMN_NAMES = {"extra_data": '{"host": "other.example"}', "created_at": "2000-01-01T00:00:00"}


def _stored(db, cid: str) -> Connection:
    db.expire_all()
    return db.query(Connection).filter(Connection.id == cid).one()


def test_post_and_put_keep_column_names_out_of_their_columns(test_client, db_session, admin_user):
    import json

    h = _admin_headers(test_client)
    r = test_client.post(
        "/api/connections",
        json={"name": "a", "kind": "ssh", "host": "h", **_COLUMN_NAMES},
        headers=h,
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    row = _stored(db_session, cid)
    assert row.host == "h" and row.created_at.year != 2000
    assert json.loads(row.extra_data) == _COLUMN_NAMES

    r = test_client.put(f"/api/connections/{cid}", json={"notes": "n", **_COLUMN_NAMES}, headers=h)
    assert r.status_code == 200, r.text
    row = _stored(db_session, cid)
    assert row.notes == "n" and row.created_at.year != 2000
    assert json.loads(row.extra_data) == _COLUMN_NAMES


def test_import_keeps_column_names_out_of_their_columns(test_client, db_session, admin_user):
    import json

    h = _admin_headers(test_client)
    body = {
        "mode": "merge",
        "connections": [{"name": "i", "kind": "ssh", "host": "h", **_COLUMN_NAMES}],
    }
    r = test_client.post("/api/connections/import", json=body, headers=h)
    assert r.status_code == 200, r.text
    row = db_session.query(Connection).filter(Connection.name == "i").one()
    assert row.host == "h" and row.created_at.year != 2000
    assert json.loads(row.extra_data) == _COLUMN_NAMES
