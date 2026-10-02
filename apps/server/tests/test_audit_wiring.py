# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end audit wiring: real requests through the auth dependencies must
land the expected audit_log rows with the right actor (user vs API key)."""

import secrets
from datetime import timedelta

from app.core.auth import create_access_token, hash_api_key
from app.modules.api_keys.models import ApiKey
from app.modules.audit.models import AuditLog

BODY = {"name": "audit-conn", "kind": "ssh"}


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _rows(db, action):
    return db.query(AuditLog).filter(AuditLog.action == action).all()


def test_connection_create_is_audited(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    r = test_client.post(
        "/api/connections", json=BODY, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 201, r.text
    conn_id = r.json()["id"]

    rows = _rows(db_session, "connection.created")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_type == "user"
    assert row.actor_label == "admin"
    assert row.object_type == "connection"
    assert row.object_id == conn_id
    assert row.object_label == "audit-conn"
    assert row.status == "success"


def test_connection_access_is_audited(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    headers = {"Authorization": f"Bearer {token}"}
    conn_id = test_client.post("/api/connections", json=BODY, headers=headers).json()["id"]

    r = test_client.post(f"/api/connections/{conn_id}/touch", headers=headers)
    assert r.status_code == 200, r.text

    rows = _rows(db_session, "connection.accessed")
    assert len(rows) == 1
    assert rows[0].object_id == conn_id
    assert rows[0].actor_label == "admin"


def test_connection_delete_is_audited(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    headers = {"Authorization": f"Bearer {token}"}
    conn_id = test_client.post("/api/connections", json=BODY, headers=headers).json()["id"]

    r = test_client.delete(f"/api/connections/{conn_id}", headers=headers)
    assert r.status_code == 204, r.text

    rows = _rows(db_session, "connection.deleted")
    assert len(rows) == 1
    assert rows[0].object_id == conn_id
    assert rows[0].object_label == "audit-conn"


def test_apikey_actor_is_recorded(test_client, db_session):
    raw = f"ah_{secrets.token_urlsafe(16)}"
    db_session.add(ApiKey(name="audit-key", hashed_key=hash_api_key(raw), permission="read_write"))
    db_session.commit()

    r = test_client.post("/api/connections", json=BODY, headers={"X-API-Key": raw})
    assert r.status_code == 201, r.text

    rows = _rows(db_session, "connection.created")
    assert len(rows) == 1
    assert rows[0].actor_type == "api_key"
    assert rows[0].actor_label == "audit-key"


def test_failed_login_is_audited(test_client, db_session, admin_user):
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401

    rows = _rows(db_session, "auth.login_failed")
    assert len(rows) == 1
    assert rows[0].status == "failure"
    assert rows[0].actor_type == "anonymous"
    assert rows[0].actor_label == "admin"


def test_successful_login_is_audited(test_client, db_session, admin_user):
    _login(test_client, "admin", "adminpass")
    rows = _rows(db_session, "auth.login")
    assert len(rows) == 1
    assert rows[0].actor_label == "admin"
    assert rows[0].actor_type == "user"


def _logout(client, **kw):
    r = client.post("/api/auth/logout", **kw)
    assert r.status_code == 200, r.text
    assert r.json() == {"detail": "Abgemeldet"}
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "refresh_token=" in set_cookie and "max-age=0" in set_cookie
    return r


def test_logout_without_a_token_is_not_audited(test_client, db_session):
    _logout(test_client)
    assert _rows(db_session, "auth.logout") == []


def test_logout_with_an_invalid_bearer_is_not_audited(test_client, db_session):
    _logout(test_client, headers={"Authorization": "Bearer garbage"})
    assert _rows(db_session, "auth.logout") == []


def test_repeated_logouts_without_a_token_write_nothing(test_client, db_session):
    for _ in range(50):
        _logout(test_client)
    assert _rows(db_session, "auth.logout") == []


def test_logout_with_only_an_expired_access_token_is_not_audited(
    test_client, db_session, admin_user
):
    expired = create_access_token({"sub": "admin"}, expires_delta=timedelta(minutes=-5))
    _logout(test_client, headers={"Authorization": f"Bearer {expired}"})
    assert _rows(db_session, "auth.logout") == []


def test_logout_twice_with_the_same_tokens_is_audited_once(test_client, db_session, admin_user):
    login = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    access, refresh = login.json()["access_token"], login.json()["refresh_token"]
    kw = {"headers": {"Authorization": f"Bearer {access}"}, "json": {"refresh_token": refresh}}
    _logout(test_client, **kw)
    _logout(test_client, **kw)
    assert len(_rows(db_session, "auth.logout")) == 1


def test_logout_with_only_the_cookie_names_the_user(test_client, db_session, admin_user):
    test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert test_client.cookies.get("refresh_token")
    _logout(test_client)  # no Authorization header, no body: only the cookie
    rows = _rows(db_session, "auth.logout")
    assert len(rows) == 1
    assert rows[0].object_label == "admin"


def test_logout_with_bearer_and_body_is_audited_once(test_client, db_session, admin_user):
    login = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    access, refresh = login.json()["access_token"], login.json()["refresh_token"]
    _logout(
        test_client,
        headers={"Authorization": f"Bearer {access}"},
        json={"refresh_token": refresh},
    )
    rows = _rows(db_session, "auth.logout")
    assert len(rows) == 1
    assert rows[0].actor_label == "admin"
    assert rows[0].actor_type == "user"


def test_server_create_is_audited(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    r = test_client.post(
        "/api/servers",
        json={"name": "audit-srv", "hostname": "host.example"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    rows = _rows(db_session, "server.created")
    assert len(rows) == 1
    assert rows[0].object_type == "server"
    assert rows[0].object_label == "audit-srv"
    assert rows[0].actor_label == "admin"


def test_user_create_is_audited(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    r = test_client.post(
        "/api/users",
        json={"username": "audituser", "password": "password123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    rows = _rows(db_session, "user.created")
    assert len(rows) == 1
    assert rows[0].object_label == "audituser"
    assert rows[0].actor_label == "admin"


def test_apikey_create_is_audited(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    r = test_client.post(
        "/api/api-keys",
        json={"name": "audit-key2", "permission": "read"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    rows = _rows(db_session, "apikey.created")
    assert len(rows) == 1
    assert rows[0].object_type == "api_key"
    assert rows[0].object_label == "audit-key2"
    assert rows[0].actor_label == "admin"
