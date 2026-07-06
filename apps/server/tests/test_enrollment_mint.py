# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Human enrollment-token minting (A5): a logged-in user mints a one-time,
access-scoped token to redeem at the ca-issuer for its mTLS client cert."""

from __future__ import annotations

from app.core.auth import hash_api_key
from app.modules.enrollment.models import EnrollmentToken


def _login(test_client, username: str, password: str) -> str:
    resp = test_client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_mint_returns_access_scoped_token(test_client, admin_user, db_session):
    token = _login(test_client, "admin", "adminpass")
    res = test_client.post("/api/enrollment/token", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["subjectId"] == "admin"  # the cert CN = username, issuer-dictated
    assert body["scope"] == "access"
    assert body["enrollPort"] == 8444
    assert body["token"]

    # The minted row is consumable: hashed with the same SHA-256 the ca-issuer
    # uses, access scope, the username as identity, still valid.
    row = (
        db_session.query(EnrollmentToken)
        .filter(EnrollmentToken.hashed_token == hash_api_key(body["token"]))
        .one()
    )
    assert row.subject_id == "admin"
    assert row.scope == "access"
    assert row.browser is False
    assert row.used_at is None
    assert row.is_valid()


def test_mint_requires_authentication(test_client):
    # No JWT -> the bootstrap door is still auth-gated.
    res = test_client.post("/api/enrollment/token")
    assert res.status_code == 401


def test_mint_uses_the_callers_identity(test_client, normal_user, db_session):
    # A non-admin user mints a token for THEIR username, not someone else's.
    token = _login(test_client, "viewer", "viewerpass")
    res = test_client.post("/api/enrollment/token", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    assert res.json()["subjectId"] == "viewer"


def test_mint_browser_flag_marks_long_lived_token(test_client, admin_user, db_session):
    # browser=true -> the ca-issuer signs a long-lived leaf (D5), for the P12 the
    # desktop exports to the browser cert store (A5c).
    token = _login(test_client, "admin", "adminpass")
    res = test_client.post(
        "/api/enrollment/token?browser=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["browser"] is True
    row = (
        db_session.query(EnrollmentToken)
        .filter(EnrollmentToken.hashed_token == hash_api_key(res.json()["token"]))
        .one()
    )
    assert row.browser is True


# ── /token/for — admin mints FOR another user (ADR 0003 decoupled door) ──────


def test_admin_mint_for_other_user(test_client, admin_user, normal_user, db_session):
    # The decoupled-enrollment door: an admin mints a token FOR another existing
    # user, who redeems it certless at :8444 — no :443 login by the new user.
    token = _login(test_client, "admin", "adminpass")
    res = test_client.post(
        "/api/enrollment/token/for",
        json={"username": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["subjectId"] == "viewer"  # cert CN = the TARGET user, not the admin
    assert body["scope"] == "access"
    row = (
        db_session.query(EnrollmentToken)
        .filter(EnrollmentToken.hashed_token == hash_api_key(body["token"]))
        .one()
    )
    assert row.subject_id == "viewer"
    assert row.used_at is None
    assert row.is_valid()


def test_mint_for_unknown_user_is_404(test_client, admin_user):
    token = _login(test_client, "admin", "adminpass")
    res = test_client.post(
        "/api/enrollment/token/for",
        json={"username": "ghost"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404, res.text


def test_mint_for_requires_admin(test_client, normal_user):
    # A non-admin must not mint tokens for other identities (rejected before the
    # user lookup, so it does not matter that "viewer" exists).
    token = _login(test_client, "viewer", "viewerpass")
    res = test_client.post(
        "/api/enrollment/token/for",
        json={"username": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403, res.text


def test_mint_for_requires_authentication(test_client):
    res = test_client.post("/api/enrollment/token/for", json={"username": "admin"})
    assert res.status_code == 401


def test_self_mint_writes_audit(test_client, admin_user, db_session):
    from app.modules.audit.models import AuditLog

    token = _login(test_client, "admin", "adminpass")
    res = test_client.post("/api/enrollment/token", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    # 3.9: minting a cert-granting token must leave an audit trail (self-mint).
    row = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "enrollment.token.minted", AuditLog.object_id == "admin")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None
    assert row.actor_id == str(admin_user.id)


def test_admin_mint_for_writes_audit(test_client, admin_user, normal_user, db_session):
    from app.modules.audit.models import AuditLog

    token = _login(test_client, "admin", "adminpass")
    res = test_client.post(
        "/api/enrollment/token/for",
        json={"username": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    # 3.9: an admin minting FOR another identity is the sensitive path — the audit
    # row records who (actor=admin) minted for whom (object_id=viewer).
    row = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "enrollment.token.minted_for",
            AuditLog.object_id == "viewer",
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None
    assert row.actor_id == str(admin_user.id)


def test_admin_mint_for_browser_flags_long_lived_leaf(
    test_client, admin_user, normal_user, db_session
):
    from app.modules.audit.models import AuditLog

    token = _login(test_client, "admin", "adminpass")
    res = test_client.post(
        "/api/enrollment/token/for",
        json={"username": "viewer", "browser": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    # 3.32: a browser=true grant for another identity is a long-lived (~1y) leaf that
    # is only revocable under enforcement — the audit detail must flag that.
    row = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "enrollment.token.minted_for",
            AuditLog.object_id == "viewer",
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None
    assert "long-lived" in row.detail and "MTLS_ENFORCE" in row.detail


def test_mint_for_writes_audit(test_client, admin_user, normal_user, db_session):
    # 6.81: the admin-mint /token/for path must leave an audit trail (3.32) — a long-lived for-another
    # grant has to be greppable. The finding described the pre-3.32 state ("it doesn't"); this pins
    # the current behaviour so the audit line can't silently regress out again.
    from app.modules.audit.models import AuditLog

    tok = _login(test_client, "admin", "adminpass")
    res = test_client.post(
        "/api/enrollment/token/for",
        json={"username": "viewer"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 200, res.text
    n = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "enrollment.token.minted_for")
        .count()
    )
    assert n == 1, f"expected exactly one enrollment audit row, got {n}"
