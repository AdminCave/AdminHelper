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
from app.modules.audit.models import AuditLog
from app.modules.users.models import User
from tests.test_mtls_scope import _gateway_headers, _req
from tests.token_claims import claims_for

MISMATCH = "ERR_CERT_USER_MISMATCH"


@pytest.fixture(autouse=True)
def _enforced(monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)


def _bearer(username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(claims_for(username))}"}


def _assert_mismatch(resp) -> None:
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"].startswith(f"{MISMATCH}: "), resp.text
    assert resp.json()["code"] == MISMATCH, resp.text


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


def test_the_mismatch_body_is_the_text_and_its_code(test_client, admin_user, normal_user):
    # The contract (R-0664): the detail word for word as before the code, the code next to it.
    resp = test_client.get(
        "/api/api-keys", headers={**_bearer("admin"), **_gateway_headers(cn="viewer")}
    )
    assert resp.status_code == 403, resp.text
    assert resp.json() == {
        "detail": "ERR_CERT_USER_MISMATCH: The client certificate belongs to another user. "
        "Sign in as that user, or register this device for yourself.",
        "code": "ERR_CERT_USER_MISMATCH",
    }


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
    refresh = create_refresh_token(claims_for("admin"))
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
    import app.core.identity as id_mod
    from app.modules.notifications.stream import authenticate_stream_user

    class _FakeDB:
        def close(self):
            pass

    class _User:
        id = 1
        username = "admin"

    monkeypatch.setattr(db_mod, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(auth_mod, "_get_user_from_token", lambda token, db: _User())
    # The fake session has no tables: the register admits both certificates here.
    monkeypatch.setattr(id_mod, "_is_revoked", lambda *a, **k: False)
    headers = {"Authorization": "Bearer tok", **_gateway_headers(cn="viewer")}
    with pytest.raises(HTTPException) as exc:
        authenticate_stream_user(_req(headers))
    assert exc.value.status_code == 403
    assert exc.value.detail.startswith(f"{MISMATCH}: ")
    assert exc.value.code == MISMATCH

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


# --- order and switch -------------------------------------------------------


def test_a_refused_login_is_audited(test_client, db_session, admin_user, normal_user):
    resp = test_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "adminpass"},
        headers=_gateway_headers(cn="viewer"),
    )
    _assert_mismatch(resp)
    rows = db_session.query(AuditLog).filter(AuditLog.action == "auth.login_failed").all()
    assert len(rows) == 1
    assert rows[0].status == "failure"
    assert rows[0].actor_label == "admin"


def test_a_refused_refresh_does_not_use_up_the_token(test_client, admin_user, normal_user):
    refresh = create_refresh_token(claims_for("admin"))
    refused = test_client.post(
        "/api/auth/refresh", json={"refresh_token": refresh}, headers=_gateway_headers(cn="viewer")
    )
    _assert_mismatch(refused)
    # Checked before the rotation: the same token still works with the user's own certificate.
    again = test_client.post(
        "/api/auth/refresh", json={"refresh_token": refresh}, headers=_gateway_headers(cn="admin")
    )
    assert again.status_code == 200, again.text


def test_a_refused_bootstrap_creates_no_user(test_client, db_session, bootstrap_token):
    body = {"token": bootstrap_token, "username": "firstadmin", "password": "a-long-password"}
    refused = test_client.post(
        "/api/auth/bootstrap", json=body, headers=_gateway_headers(cn="someone-else")
    )
    _assert_mismatch(refused)
    assert db_session.query(User).count() == 0
    again = test_client.post(
        "/api/auth/bootstrap", json=body, headers=_gateway_headers(cn="firstadmin")
    )
    assert again.status_code == 201, again.text


# --- enforced: no certificate, no sign-in (R-0900) --------------------------------
NO_CERT = "No valid client certificate"


def test_enforced_login_without_a_certificate_is_refused_and_audited(
    test_client, db_session, admin_user
):
    # The right password does not help.
    resp = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == NO_CERT
    rows = db_session.query(AuditLog).filter(AuditLog.action == "auth.login_failed").all()
    assert len(rows) == 1
    assert rows[0].actor_label == "admin"
    assert db_session.query(AuditLog).filter(AuditLog.action == "auth.login").count() == 0


def test_enforced_refresh_without_a_certificate_is_refused_and_keeps_the_token(
    test_client, admin_user
):
    refresh = create_refresh_token(claims_for("admin"))
    refused = test_client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == NO_CERT
    again = test_client.post(
        "/api/auth/refresh", json={"refresh_token": refresh}, headers=_gateway_headers(cn="admin")
    )
    assert again.status_code == 200, again.text


def test_enforced_refresh_without_a_certificate_is_audited(test_client, db_session, admin_user):
    refresh = create_refresh_token(claims_for("admin"))
    refused = test_client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert refused.status_code == 403, refused.text
    rows = db_session.query(AuditLog).filter(AuditLog.action == "auth.refresh_failed").all()
    assert len(rows) == 1
    assert rows[0].status == "failure"
    assert rows[0].actor_label == "admin"
    assert rows[0].object_label == "admin"


def test_enforced_bootstrap_without_a_certificate_creates_no_user(
    test_client, db_session, bootstrap_token
):
    body = {"token": bootstrap_token, "username": "firstadmin", "password": "a-long-password"}
    refused = test_client.post("/api/auth/bootstrap", json=body)
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == NO_CERT
    assert db_session.query(User).count() == 0
    again = test_client.post(
        "/api/auth/bootstrap", json=body, headers=_gateway_headers(cn="firstadmin")
    )
    assert again.status_code == 201, again.text


def test_permissive_sign_in_without_a_certificate_still_passes(
    test_client, admin_user, monkeypatch
):
    monkeypatch.setattr(config, "MTLS_ENFORCE", False)
    login = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert login.status_code == 200, login.text
    refresh = create_refresh_token(claims_for("admin"))
    resp = test_client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200, resp.text


def test_the_binding_holds_in_permissive_mode_too(
    test_client, admin_user, normal_user, monkeypatch
):
    monkeypatch.setattr(config, "MTLS_ENFORCE", False)
    resp = test_client.get(
        "/api/api-keys", headers={**_bearer("admin"), **_gateway_headers(cn="viewer")}
    )
    _assert_mismatch(resp)


# --- logout: not bound, on purpose (R-0282) ------------------------------------------
# Logging out only ends the tokens it is given; it grants nothing and shows nothing. It
# works with any certificate, also one the server no longer admits, so a device whose
# certificate was revoked can still end its session.


def test_logout_with_another_users_certificate_ends_the_presented_token(
    test_client, admin_user, normal_user
):
    viewer = _bearer("viewer")
    own = {**viewer, **_gateway_headers(cn="viewer")}
    assert test_client.get("/api/auth/me", headers=own).status_code == 200
    resp = test_client.post("/api/auth/logout", headers={**viewer, **_gateway_headers(cn="admin")})
    assert resp.status_code == 200, resp.text
    me = test_client.get("/api/auth/me", headers=own)
    assert me.status_code == 401, me.text


def test_logout_with_a_revoked_certificate_ends_the_presented_token(
    test_client, db_session, admin_user
):
    from tests.test_certificate_check import _leaf, _record

    admin = _bearer("admin")
    revoked_headers, revoked = _leaf("admin")
    _record(db_session, revoked, "admin", revoked=True)
    fresh_headers, _ = _leaf("admin")
    assert test_client.get("/api/auth/me", headers={**admin, **fresh_headers}).status_code == 200
    resp = test_client.post("/api/auth/logout", headers={**admin, **revoked_headers})
    assert resp.status_code == 200, resp.text
    me = test_client.get("/api/auth/me", headers={**admin, **fresh_headers})
    assert me.status_code == 401, me.text
