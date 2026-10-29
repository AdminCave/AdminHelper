# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tokens name their account by its id (`uid`); the name in `sub` decides nothing."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import ALGORITHM, SECRET_KEY
from app.modules.users.models import User


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _claims(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def _token(token_type: str, **claims) -> str:
    # The shape create_access_token/create_refresh_token write, with the identity claims chosen.
    now = datetime.now(timezone.utc)
    payload = {
        "type": token_type,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "jti": str(uuid.uuid4()),
        **claims,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _user(db_session, username: str) -> User:
    db_session.expire_all()
    return db_session.query(User).filter(User.username == username).one()


def test_login_and_refresh_issue_tokens_with_the_account_id(test_client, db_session, admin_user):
    tokens = _login(test_client, "admin", "adminpass")
    for token in (tokens["access_token"], tokens["refresh_token"]):
        assert _claims(token)["uid"] == admin_user.id
        assert _claims(token)["sub"] == "admin"

    r = test_client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200, r.text
    for token in (r.json()["access_token"], r.json()["refresh_token"]):
        assert _claims(token)["uid"] == admin_user.id


def test_a_token_without_an_account_id_does_not_hold(test_client, db_session, admin_user):
    # Every token issued before the update: valid signature and times, but no uid.
    access = _token("access", sub="admin")
    refresh = _token("refresh", sub="admin")

    assert test_client.get("/api/auth/me", headers=_bearer(access)).status_code == 401
    r = test_client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401, r.text


def test_a_replayed_token_of_a_deleted_namesake_leaves_the_new_account_alone(
    test_client, db_session, admin_user
):
    admin = _bearer(_login(test_client, "admin", "adminpass")["access_token"])
    created = test_client.post(
        "/api/users", json={"username": "bob", "password": "password1"}, headers=admin
    )
    assert created.status_code == 201, created.text
    old_refresh = _login(test_client, "bob", "password1")["refresh_token"]
    rotated = test_client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200, rotated.text  # old_refresh is revoked now

    old_id = _user(db_session, "bob").id
    deleted = test_client.delete(f"/api/users/{old_id}", headers=admin)
    assert deleted.status_code in (200, 204), deleted.text
    created = test_client.post(
        "/api/users", json={"username": "bob", "password": "password2"}, headers=admin
    )
    assert created.status_code == 201, created.text
    new_bob = _login(test_client, "bob", "password2")
    watermark = _user(db_session, "bob").tokens_valid_after

    replay = test_client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert replay.status_code == 401, replay.text

    assert _user(db_session, "bob").tokens_valid_after == watermark
    me = test_client.get("/api/auth/me", headers=_bearer(new_bob["access_token"]))
    assert me.status_code == 200, me.text
    r = test_client.post("/api/auth/refresh", json={"refresh_token": new_bob["refresh_token"]})
    assert r.status_code == 200, r.text


def test_the_account_id_decides_not_the_name(test_client, db_session, admin_user):
    token = _token("access", sub="someone-else", uid=admin_user.id)
    me = test_client.get("/api/auth/me", headers=_bearer(token))
    assert me.status_code == 200, me.text
    assert me.json()["username"] == "admin"
