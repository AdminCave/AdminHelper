# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PUT /api/users/{id} names the changed fields in the detail of user.updated; of the
values only the new admin flag lands in the row."""

from app.core.auth import hash_password
from app.modules.audit.models import AuditLog
from app.modules.servers.models import Server
from app.modules.users.models import User

ACTION = "user.updated"
NEW_PASSWORD = "fresh-pw-7b2e"


def _headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _rows(db):
    return db.query(AuditLog).filter(AuditLog.action == ACTION).all()


def _cells(row):
    return [str(getattr(row, col.key)) for col in AuditLog.__table__.columns]


def _servers(db):
    db.add_all(
        [
            Server(id="srv-aud-a", name="A", hostname="a.example"),
            Server(id="srv-aud-b", name="B", hostname="b.example"),
        ]
    )
    db.commit()
    return ["srv-aud-a", "srv-aud-b"]


def _user(db, name="audit-target", *, is_admin=False, server_ids=()):
    user = User(username=name, hashed_password=hash_password("oldpass99"), is_admin=is_admin)
    user.servers = [db.get(Server, sid) for sid in server_ids]
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _put(client, db, user, body):
    """PUT the body and return the one user.updated row it wrote."""
    res = client.put(f"/api/users/{user.id}", headers=_headers(client), json=body)
    assert res.status_code == 200, res.text
    rows = _rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert (row.actor_type, row.actor_label) == ("user", "admin")
    assert (row.object_type, row.object_id, row.object_label) == (
        "user",
        str(user.id),
        user.username,
    )
    assert row.status == "success"
    return row


def test_password_only(test_client, db_session, admin_user):
    user = _user(db_session)
    row = _put(test_client, db_session, user, {"password": NEW_PASSWORD})
    assert row.detail == "password"
    db_session.refresh(user)
    for cell in _cells(row):
        assert NEW_PASSWORD not in cell
        assert user.hashed_password not in cell


def test_promotion(test_client, db_session, admin_user):
    user = _user(db_session)
    row = _put(test_client, db_session, user, {"is_admin": True})
    assert row.detail == "is_admin=true"


def test_demotion_with_two_admins(test_client, db_session, admin_user):
    user = _user(db_session, "admin2", is_admin=True)
    row = _put(test_client, db_session, user, {"is_admin": False})
    assert row.detail == "is_admin=false"


def test_new_server_assignment(test_client, db_session, admin_user):
    ids = _servers(db_session)
    user = _user(db_session)
    row = _put(test_client, db_session, user, {"server_ids": ids})
    assert row.detail == "server_ids"


def test_all_together(test_client, db_session, admin_user):
    ids = _servers(db_session)
    user = _user(db_session)
    row = _put(
        test_client,
        db_session,
        user,
        {"password": NEW_PASSWORD, "is_admin": True, "server_ids": ids},
    )
    assert row.detail == "password, is_admin=true, server_ids"
    for cell in _cells(row):
        assert NEW_PASSWORD not in cell


def test_unchanged_values_leave_detail_empty(test_client, db_session, admin_user):
    ids = _servers(db_session)
    user = _user(db_session, server_ids=ids)
    row = _put(
        test_client,
        db_session,
        user,
        {"is_admin": False, "server_ids": list(reversed(ids))},
    )
    assert row.detail is None


def test_demoting_last_admin_writes_no_row(test_client, db_session, admin_user):
    res = test_client.put(
        f"/api/users/{admin_user.id}", headers=_headers(test_client), json={"is_admin": False}
    )
    assert res.status_code == 400, res.text
    assert _rows(db_session) == []
    # The same route on the same user does write once it succeeds.
    row = _put(test_client, db_session, admin_user, {"is_admin": True})
    assert row.detail is None
