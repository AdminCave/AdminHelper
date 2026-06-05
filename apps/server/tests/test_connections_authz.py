# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Authorization matrix for /api/connections writes — INTENT LOCK (regression).

A security audit flagged that `ApiKeyOrUser(require_write=True, require_admin=True)`
lets a (non-admin) `read_write` API key write connections. That is **by design**,
not a bug:

- `docs/admin/users.html`: `read_write` = "read and write".
- `docs/en/admin/extension.html`: warns to *never* give the extension a key with
  "connection-write ... privileges" — i.e. a read_write key has connection-write
  by design.
- It is also the only write endpoint guarded by `require_write`; rejecting API
  keys here would make the `read_write` permission dead.

So the policy is: **write = a read_write API key OR an admin JWT user**. This test
pins that matrix so it is not "fixed" into rejecting API keys (which would break
the documented feature). For genuinely admin-only/no-API-key endpoints the code
uses `get_current_admin` directly instead.
"""

import secrets

from app.core.auth import hash_api_key
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
