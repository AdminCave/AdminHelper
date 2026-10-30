# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A new user holds only tokens issued from his creation on (users.tokens_valid_after)."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app import cli
from app.core.auth import _get_user_from_token, hash_api_key, hash_password
from app.core.config import ALGORITHM, SECRET_KEY
from app.core.time import utcnow_naive
from app.modules.users import auth_router
from app.modules.users.models import User
from tests.token_claims import claims_for


def _token(username: str, token_type: str, issued_at: datetime) -> str:
    # The shape of create_access_token/create_refresh_token with a chosen `iat`.
    return jwt.encode(
        {
            **claims_for(username),
            "type": token_type,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "iat": issued_at,
            "jti": str(uuid.uuid4()),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def test_tokens_issued_before_a_user_exists_do_not_hold_for_him(test_client, admin_user):
    # Tokens carrying the new user's name and id, issued a minute before he exists: only
    # the watermark tells them apart from his own.
    earlier = datetime.now(timezone.utc) - timedelta(seconds=60)

    admin = _login(test_client, "admin", "adminpass")["access_token"]
    created = test_client.post(
        "/api/users", json={"username": "bob", "password": "password1"}, headers=_bearer(admin)
    )
    assert created.status_code == 201, created.text
    access = _token("bob", "access", earlier)
    refresh = _token("bob", "refresh", earlier)

    assert test_client.get("/api/auth/me", headers=_bearer(access)).status_code == 401
    assert test_client.post("/api/auth/refresh", json={"refresh_token": refresh}).status_code == 401

    fresh = _login(test_client, "bob", "password1")["access_token"]
    me = test_client.get("/api/auth/me", headers=_bearer(fresh))
    assert me.status_code == 200, me.text
    assert me.json()["username"] == "bob"


def test_a_new_user_holds_tokens_from_the_whole_second_of_his_creation(db_session):
    before = utcnow_naive().replace(microsecond=0)
    user = User(username="dave", hashed_password=hash_password("password1"))
    db_session.add(user)
    db_session.commit()

    watermark = user.tokens_valid_after
    assert watermark is not None
    assert watermark.microsecond == 0
    assert before <= watermark <= utcnow_naive()

    issued = watermark.replace(tzinfo=timezone.utc)
    assert _get_user_from_token(_token("dave", "access", issued), db_session) is not None
    a_second_earlier = issued - timedelta(seconds=1)
    assert _get_user_from_token(_token("dave", "access", a_second_earlier), db_session) is None


def test_the_creation_watermark_holds_off_the_api_too(db_session):
    assert cli.create_admin(db_session, "carol", "password1") == 0
    user = db_session.query(User).filter_by(username="carol").one()
    assert user.tokens_valid_after is not None


def test_the_tokens_of_the_bootstrap_answer_hold(test_client, tmp_path, monkeypatch):
    # The bootstrap issues tokens in the second it creates the user.
    raw = "bootstrap-token-for-watermark"
    token_file = tmp_path / ".bootstrap_token"
    token_file.write_text(hash_api_key(raw))
    monkeypatch.setattr(auth_router, "BOOTSTRAP_TOKEN_FILE", token_file)
    monkeypatch.setattr(auth_router, "BOOTSTRAP_SETUP_FILE", tmp_path / ".bootstrap_setup")

    resp = test_client.post(
        "/api/auth/bootstrap",
        json={"token": raw, "username": "firstadmin", "password": "a-long-password"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert test_client.get("/api/auth/me", headers=_bearer(body["access_token"])).status_code == 200
    rot = test_client.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert rot.status_code == 200, rot.text


def test_the_admin_from_admin_password_holds_tokens_from_the_second_of_its_creation(
    db_session, monkeypatch
):
    import app.main as m

    monkeypatch.setattr(m, "ADMIN_PASSWORD", "supersecret")
    m._ensure_admin(db_session)
    user = db_session.query(User).filter_by(username="admin").one()

    watermark = user.tokens_valid_after
    assert watermark is not None
    assert watermark.microsecond == 0

    issued = watermark.replace(tzinfo=timezone.utc)
    assert _get_user_from_token(_token("admin", "access", issued), db_session) is not None
    a_second_earlier = issued - timedelta(seconds=1)
    assert _get_user_from_token(_token("admin", "access", a_second_earlier), db_session) is None
