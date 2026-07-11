# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Identity revocation (F1, ADR 0001 §3.4 — the fast cut-off without CRL).

Deleting a user/server writes a RevokedIdentity so the ca-issuer refuses to renew
its cert (lever 1) and the data plane rejects it on sight (lever 2, in
test_mtls_scope). Usernames are reusable, so creating a user clears any stale
revocation from a former namesake."""

from __future__ import annotations

import app.modules.servers.router as servers_router
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT
from app.modules.enrollment.models import (
    RevokedIdentity,
    clear_revocation,
    is_identity_revoked,
    revoke_identity,
)
from app.modules.servers.models import Server


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


def test_clear_revocation_removes_row(db_session):
    revoke_identity(db_session, "x", SCOPE_ACCESS)
    db_session.commit()
    assert clear_revocation(db_session, "x", SCOPE_ACCESS) == 1
    db_session.commit()
    assert not is_identity_revoked(db_session, "x", SCOPE_ACCESS)


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


def test_create_user_clears_a_stale_revocation(test_client, admin_user, db_session):
    # A former namesake left a revocation behind.
    revoke_identity(db_session, "bob", SCOPE_ACCESS)
    db_session.commit()
    assert is_identity_revoked(db_session, "bob", SCOPE_ACCESS)

    token = _login(test_client, "admin", "adminpass")
    created = test_client.post(
        "/api/users",
        json={"username": "bob", "password": "password1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 201, created.text
    # The new bob must not inherit the old revocation, or it could never renew.
    assert not is_identity_revoked(db_session, "bob", SCOPE_ACCESS)


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
