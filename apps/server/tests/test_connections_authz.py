# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Authorization matrix for /api/connections writes — INTENT LOCK (regression).

A security audit flagged that `ApiKeyOrUser(require_write=True, require_admin=True)`
lets a (non-admin) `read_write` API key write connections. That is **by design**,
not a bug:

- `docs/admin/users.html`: `read_write` = "read and write" — i.e. a read_write
  key has connection-write by design.
- It is also the only write endpoint guarded by `require_write`; rejecting API
  keys here would make the `read_write` permission dead.

So the policy is: **write = a read_write API key OR an admin JWT user**. This test
pins that matrix so it is not "fixed" into rejecting API keys (which would break
the documented feature). For genuinely admin-only/no-API-key endpoints the code
uses `get_current_admin` directly instead.
"""

import logging
import secrets
from datetime import timedelta

from app.core.auth import create_access_token, hash_api_key
from app.modules.api_keys.models import ApiKey

BODY = {"name": "authz-regression", "kind": "ssh"}


def _api_key(db, permission: str) -> str:
    raw = f"ah_{secrets.token_urlsafe(16)}"
    db.add(ApiKey(name=f"k-{permission}", hashed_key=hash_api_key(raw), permission=permission))
    db.commit()
    return raw


def _login(client, username: str, password: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestConnectionsWriteAuthz:
    def test_read_write_apikey_can_create_BY_DESIGN(self, test_client, db_session):
        # INTENT: read_write keys are documented to read AND write. Must stay 201.
        key = _api_key(db_session, "read_write")
        r = test_client.post("/api/connections", json=BODY, headers={"X-API-Key": key})
        assert r.status_code == 201, r.text

    def test_read_apikey_cannot_create(self, test_client, db_session):
        key = _api_key(db_session, "read")
        r = test_client.post("/api/connections", json=BODY, headers={"X-API-Key": key})
        assert r.status_code == 403, r.text

    def test_nonadmin_jwt_cannot_create(self, test_client, db_session, normal_user):
        token = _login(test_client, "viewer", "viewerpass")
        r = test_client.post(
            "/api/connections", json=BODY, headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 403, r.text

    def test_admin_jwt_can_create(self, test_client, db_session, admin_user):
        token = _login(test_client, "admin", "adminpass")
        r = test_client.post(
            "/api/connections", json=BODY, headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 201, r.text

    def test_read_apikey_can_read(self, test_client, db_session):
        key = _api_key(db_session, "read")
        r = test_client.get("/api/connections", headers={"X-API-Key": key})
        assert r.status_code == 200, r.text


def test_apikey_via_query_param_is_audited(test_client, db_session, caplog):
    """3.87: the ?api_key= fallback still authenticates but logs a WARNING naming the
    key, so the operator can rotate the one that just leaked into the access logs; the
    header path stays quiet."""
    key = _api_key(db_session, "read")
    with caplog.at_level(logging.WARNING, logger="adminhelper.auth"):
        r = test_client.get(f"/api/connections?api_key={key}")
    assert r.status_code == 200, r.text
    assert any("Query-Parameter" in rec.message for rec in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="adminhelper.auth"):
        r = test_client.get("/api/connections", headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    assert not any("Query-Parameter" in rec.message for rec in caplog.records)


class TestEveryPresentedCredentialMustHold:
    """R-0054: ApiKeyOrUser checks every credential a request presents before it decides.
    A valid key next to a broken bearer, or a valid bearer next to an unknown key, is a 401 —
    the valid one no longer carries the other through. Both valid: the key decides, as when it
    was checked first. One credential alone keeps the matrix above unchanged."""

    def _assert_unauthenticated(self, r):
        assert r.status_code == 401, r.text
        assert r.json()["detail"] == "Nicht authentifiziert"
        assert r.headers["www-authenticate"] == "Bearer"

    def test_valid_key_with_invalid_bearer(self, test_client, db_session):
        key = _api_key(db_session, "read")
        r = test_client.get(
            "/api/connections", headers={"X-API-Key": key, "Authorization": "Bearer not-a-jwt"}
        )
        self._assert_unauthenticated(r)

    def test_valid_key_with_expired_bearer(self, test_client, db_session, admin_user):
        key = _api_key(db_session, "read")
        expired = create_access_token({"sub": "admin"}, expires_delta=timedelta(seconds=-10))
        r = test_client.get(
            "/api/connections", headers={"X-API-Key": key, "Authorization": f"Bearer {expired}"}
        )
        self._assert_unauthenticated(r)

    def test_valid_key_with_another_scheme_or_no_token(self, test_client, db_session):
        key = _api_key(db_session, "read")
        for authorization in ("Basic x", "Bearer"):
            r = test_client.get(
                "/api/connections", headers={"X-API-Key": key, "Authorization": authorization}
            )
            self._assert_unauthenticated(r)

    def test_valid_bearer_with_unknown_key(self, test_client, db_session, admin_user):
        token = _login(test_client, "admin", "adminpass")
        r = test_client.get(
            "/api/connections",
            headers={"Authorization": f"Bearer {token}", "X-API-Key": "ah_unknown"},
        )
        self._assert_unauthenticated(r)

    def test_valid_bearer_with_unknown_query_key(self, test_client, db_session, admin_user):
        token = _login(test_client, "admin", "adminpass")
        r = test_client.get(
            "/api/connections?api_key=ah_unknown", headers={"Authorization": f"Bearer {token}"}
        )
        self._assert_unauthenticated(r)

    def test_both_valid_the_key_decides(self, test_client, db_session, admin_user):
        # The admin bearer alone would create (201); with a read key next to it the key
        # decides, and a read key may not write.
        key = _api_key(db_session, "read")
        token = _login(test_client, "admin", "adminpass")
        r = test_client.post(
            "/api/connections",
            json=BODY,
            headers={"X-API-Key": key, "Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == "Schreibzugriff erforderlich"
