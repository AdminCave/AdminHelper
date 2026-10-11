# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Identity revocation (F1, ADR 0001 §3.4 — the fast cut-off without CRL).

Deleting a user/server writes a RevokedIdentity so the ca-issuer refuses to renew
its cert (lever 1) and the data plane rejects it on sight (lever 2, in
test_mtls_scope). The revocation is a point in time (R-0224): usernames are
reusable, and a new user's certificates, issued after it, pass while the former
namesake's stay revoked."""

from __future__ import annotations

from datetime import timedelta

import app.modules.servers.router as servers_router
from app.core import config
from app.core.auth import create_access_token
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT
from app.core.time import utcnow_naive
from app.modules.enrollment.models import (
    RevokedIdentity,
    is_identity_revoked,
    revoke_identity,
)
from app.modules.servers.models import Server
from tests.test_mtls_scope import _gateway_headers


def _login(client, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# --- helpers (unit) ----------------------------------------------------------


def test_revoke_identity_is_idempotent(db_session):
    revoke_identity(db_session, "x", SCOPE_ACCESS)
    revoke_identity(db_session, "x", SCOPE_ACCESS)
    db_session.commit()
    assert (
        db_session.query(RevokedIdentity).filter_by(subject_id="x", scope=SCOPE_ACCESS).count() == 1
    )
    assert is_identity_revoked(db_session, "x", SCOPE_ACCESS)


def test_scope_is_part_of_the_revocation_key(db_session):
    revoke_identity(db_session, "dual", SCOPE_ACCESS)
    db_session.commit()
    assert is_identity_revoked(db_session, "dual", SCOPE_ACCESS)
    assert not is_identity_revoked(db_session, "dual", SCOPE_AGENT)


# --- integration: delete/create flows ----------------------------------------


def test_delete_user_revokes_its_access_identity(test_client, admin_user, db_session):
    token = _login(test_client, "admin", "adminpass")
    headers = {"Authorization": f"Bearer {token}"}

    created = test_client.post(
        "/api/users",
        json={"username": "alice", "password": "password1", "is_admin": False},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    deleted = test_client.delete(f"/api/users/{user_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert is_identity_revoked(db_session, "alice", SCOPE_ACCESS)


def test_delete_server_revokes_its_tunnel_identity(
    test_client, admin_user, db_session, monkeypatch
):
    # The delete handler best-effort calls the monitoring cleanup; stub it out.
    monkeypatch.setattr(servers_router.httpx, "delete", lambda *a, **k: None)

    db_session.add(Server(id="srv-xyz", name="web1", hostname="web1.example"))
    db_session.commit()

    token = _login(test_client, "admin", "adminpass")
    deleted = test_client.delete(
        "/api/servers/srv-xyz", headers={"Authorization": f"Bearer {token}"}
    )
    assert deleted.status_code == 204, deleted.text
    # CN = stable server_id, tunnel scope (the agent's enrolled identity).
    assert is_identity_revoked(db_session, "srv-xyz", SCOPE_AGENT)


def test_oversized_forwarded_cert_header_skips_parse(monkeypatch):
    # 4.132: an oversized X-Client-Cert must be rejected by the size cap BEFORE unquote()+parse,
    # bounding CPU/memory. Spy on the parse to prove it is skipped for a huge header.
    import app.core.identity as identity_mod

    called = {"parse": False}

    def _spy(*_a, **_k):
        called["parse"] = True
        raise ValueError("parse must not be reached")

    monkeypatch.setattr(identity_mod.x509, "load_pem_x509_certificate", _spy)

    class _FakeRequest:
        def __init__(self, headers):
            self.headers = headers

    req = _FakeRequest({"x-client-verify": "SUCCESS", "x-client-cert": "x" * 20000})
    ident = identity_mod.get_client_identity(req)
    assert ident.verified is False
    assert called["parse"] is False, "parse must be skipped for an oversized header (4.132)"


# --- the revocation as a point in time (R-0224) ------------------------------


def _revoked_at(db, subject_id: str, scope: str = SCOPE_ACCESS):
    return (
        db.query(RevokedIdentity.revoked_at).filter_by(subject_id=subject_id, scope=scope).scalar()
    )


def test_revoking_again_moves_the_point_in_time(db_session):
    revoke_identity(db_session, "x", SCOPE_ACCESS)
    db_session.commit()
    earlier = utcnow_naive() - timedelta(days=1)
    db_session.query(RevokedIdentity).filter_by(subject_id="x").update({"revoked_at": earlier})
    db_session.commit()

    revoke_identity(db_session, "x", SCOPE_ACCESS)
    db_session.commit()
    assert _revoked_at(db_session, "x") > earlier


def test_only_a_certificate_issued_up_to_the_revocation_is_revoked(db_session):
    revoke_identity(db_session, "x", SCOPE_ACCESS)
    db_session.commit()
    revoked_at = _revoked_at(db_session, "x")

    assert is_identity_revoked(db_session, "x", SCOPE_ACCESS, revoked_at - timedelta(hours=1))
    assert is_identity_revoked(db_session, "x", SCOPE_ACCESS, revoked_at)
    assert not is_identity_revoked(db_session, "x", SCOPE_ACCESS, revoked_at + timedelta(seconds=1))


def test_a_new_user_keeps_the_former_namesakes_certificates_out(
    test_client, admin_user, db_session, monkeypatch
):
    # A former bob was deleted. Taking the name again leaves the revocation in place:
    # his old certificate stays out, the new bob's later one gets in.
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    revoke_identity(db_session, "bob", SCOPE_ACCESS)
    db_session.commit()
    revoked_at = _revoked_at(db_session, "bob")

    admin = {
        "Authorization": f"Bearer {create_access_token({'sub': 'admin'})}",
        **_gateway_headers(cn="admin"),
    }
    created = test_client.post(
        "/api/users", json={"username": "bob", "password": "password1"}, headers=admin
    )
    assert created.status_code == 201, created.text
    assert _revoked_at(db_session, "bob") == revoked_at

    bob = {"Authorization": f"Bearer {create_access_token({'sub': 'bob'})}"}
    old = _gateway_headers(cn="bob", not_before=revoked_at - timedelta(days=1))
    new = _gateway_headers(cn="bob", not_before=revoked_at + timedelta(seconds=2))
    assert test_client.get("/api/users/me/servers", headers={**bob, **old}).status_code == 403
    resp = test_client.get("/api/users/me/servers", headers={**bob, **new})
    assert resp.status_code == 200, resp.text
