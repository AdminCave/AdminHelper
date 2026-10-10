# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Under mTLS the client certificate belongs to the signed-in user (R-0223).

A verified identity has to carry the access scope and the user's name as its CN
wherever a user comes from a JWT or credentials: the API, the certificate-issuing
routes, the notification stream, login, refresh and bootstrap. API keys belong to
no user and stay as they are; without a verified identity there is nothing to
check.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import config
from app.core.auth import create_access_token, create_refresh_token, hash_api_key
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT
from app.modules.api_keys.models import ApiKey
from tests.test_mtls_scope import _gateway_headers, _req

MISMATCH = "ERR_CERT_USER_MISMATCH"


@pytest.fixture(autouse=True)
def _enforced(monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)


def _bearer(username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def _assert_mismatch(resp) -> None:
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"].startswith(f"{MISMATCH}: "), resp.text


# --- API routes -------------------------------------------------------------


def test_own_certificate_and_jwt_pass(test_client, admin_user):
    resp = test_client.get(
        "/api/api-keys", headers={**_bearer("admin"), **_gateway_headers(cn="admin")}
    )
    assert resp.status_code == 200, resp.text


def test_another_users_certificate_is_refused_on_an_api_route(test_client, admin_user, normal_user):
    resp = test_client.get(
        "/api/api-keys", headers={**_bearer("admin"), **_gateway_headers(cn="viewer")}
    )
    _assert_mismatch(resp)


def test_an_api_key_is_bound_to_no_user(test_client, db_session, normal_user):
    raw = "binding-read-key"
    db_session.add(ApiKey(name="k", hashed_key=hash_api_key(raw), permission="read"))
    db_session.commit()
    resp = test_client.get(
        "/api/connections", headers={"X-API-Key": raw, **_gateway_headers(cn="viewer")}
    )
    assert resp.status_code == 200, resp.text


def test_the_bearer_path_of_key_or_user_routes_is_bound(test_client, admin_user, normal_user):
    resp = test_client.get(
        "/api/connections", headers={**_bearer("admin"), **_gateway_headers(cn="viewer")}
    )
    _assert_mismatch(resp)


def test_without_a_verified_identity_nothing_is_bound(test_client, admin_user, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", False)
    resp = test_client.get("/api/api-keys", headers=_bearer("admin"))
    assert resp.status_code == 200, resp.text


# --- certificate issuing ----------------------------------------------------


def test_the_issuing_route_refuses_another_users_certificate(test_client, admin_user, normal_user):
    resp = test_client.post(
        "/api/enrollment/token", headers={**_bearer("admin"), **_gateway_headers(cn="viewer")}
    )
    _assert_mismatch(resp)


def test_the_issuing_route_refuses_a_tunnel_certificate(test_client, admin_user):
    resp = test_client.post(
        "/api/enrollment/token",
        headers={**_bearer("admin"), **_gateway_headers(cn="admin", ou=SCOPE_AGENT)},
    )
    _assert_mismatch(resp)


def test_the_issuing_route_accepts_the_users_own_certificate(test_client, admin_user):
    resp = test_client.post(
        "/api/enrollment/token", headers={**_bearer("admin"), **_gateway_headers(cn="admin")}
    )
    assert resp.status_code == 200, resp.text


# --- login, refresh, stream, bootstrap --------------------------------------


@pytest.mark.parametrize("password", ["adminpass", "wrong-password"])
def test_login_with_another_users_certificate_is_refused_whatever_the_password(
    test_client, admin_user, normal_user, password
):
    resp = test_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": password},
        headers=_gateway_headers(cn="viewer"),
    )
    _assert_mismatch(resp)


def test_login_with_the_users_own_certificate_passes(test_client, admin_user):
    resp = test_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "adminpass"},
        headers=_gateway_headers(cn="admin", ou=SCOPE_ACCESS),
    )
    assert resp.status_code == 200, resp.text


def test_refresh_with_another_users_certificate_is_refused(test_client, admin_user, normal_user):
    refresh = create_refresh_token({"sub": "admin"})
    resp = test_client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh},
        headers=_gateway_headers(cn="viewer"),
    )
    _assert_mismatch(resp)


def test_opening_the_stream_with_another_users_certificate_is_refused(monkeypatch):
    # At the dependency, not through the client: an admitted stream never ends, so a
    # regression would hang instead of fail. Session and token as in test_stream.py.
    import app.core.auth as auth_mod
    import app.core.database as db_mod
    from app.modules.notifications.stream import authenticate_stream_user

    class _FakeDB:
        def close(self):
            pass

    class _User:
        id = 1
        username = "admin"

    monkeypatch.setattr(db_mod, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(auth_mod, "_get_user_from_token", lambda token, db: _User())
    headers = {"Authorization": "Bearer tok", **_gateway_headers(cn="viewer")}
    with pytest.raises(HTTPException) as exc:
        authenticate_stream_user(_req(headers))
    assert exc.value.status_code == 403
    assert exc.value.detail.startswith(f"{MISMATCH}: ")

    own = {"Authorization": "Bearer tok", **_gateway_headers(cn="admin")}
    assert authenticate_stream_user(_req(own)) == 1


@pytest.fixture()
def bootstrap_token(tmp_path, monkeypatch):
    import app.modules.users.auth_router as auth_router

    raw = "bootstrap-token-for-binding"
    token_file = tmp_path / ".bootstrap_token"
    token_file.write_text(hash_api_key(raw))
    monkeypatch.setattr(auth_router, "BOOTSTRAP_TOKEN_FILE", token_file)
    monkeypatch.setattr(auth_router, "BOOTSTRAP_SETUP_FILE", tmp_path / ".bootstrap_setup")
    return raw


def test_bootstrap_with_another_users_certificate_is_refused(test_client, bootstrap_token):
    resp = test_client.post(
        "/api/auth/bootstrap",
        json={"token": bootstrap_token, "username": "firstadmin", "password": "a-long-password"},
        headers=_gateway_headers(cn="someone-else"),
    )
    _assert_mismatch(resp)


def test_bootstrap_with_the_new_users_certificate_passes(test_client, bootstrap_token):
    resp = test_client.post(
        "/api/auth/bootstrap",
        json={"token": bootstrap_token, "username": "firstadmin", "password": "a-long-password"},
        headers=_gateway_headers(cn="firstadmin"),
    )
    assert resp.status_code == 201, resp.text
