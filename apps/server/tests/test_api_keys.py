# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""api_keys router (6.144). permission is a Literal['read','read_write'] so Pydantic rejects anything
else with 422 (no ghost permissions), and DELETE returns 204 on success / 404 for an unknown id.
Create/list were previously only covered as a side effect of other suites."""


def _login(test_client):
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_key(test_client, headers, permission="read"):
    return test_client.post(
        "/api/api-keys", json={"name": "k", "permission": permission}, headers=headers
    )


def test_create_then_delete_api_key_204(test_client, admin_user, db_session):
    headers = _login(test_client)
    created = _create_key(test_client, headers)
    assert created.status_code == 201, created.text
    assert created.json()["key"]  # the raw key is returned exactly once, on creation
    key_id = created.json()["id"]

    resp = test_client.delete(f"/api/api-keys/{key_id}", headers=headers)
    assert resp.status_code == 204


def test_delete_unknown_api_key_404(test_client, admin_user, db_session):
    headers = _login(test_client)
    resp = test_client.delete("/api/api-keys/999999", headers=headers)
    assert resp.status_code == 404


def test_create_rejects_invalid_permission_422(test_client, admin_user, db_session):
    # permission is Literal['read','read_write'] — Pydantic rejects anything else before the router,
    # so a typo'd or escalated permission can never create a key.
    headers = _login(test_client)
    resp = _create_key(test_client, headers, permission="superadmin")
    assert resp.status_code == 422
