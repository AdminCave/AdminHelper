# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1594: os_type is a platform value. POST/PUT /api/servers take linux, windows, freebsd,
opnsense, other or null and refuse free text with 422; GET returns the stored value."""

import pytest

from app.modules.servers.models import Server

PLATFORMS = ("linux", "windows", "freebsd", "opnsense", "other")


def _headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _assert_os_type_error(r):
    detail = r.json()["detail"]
    assert isinstance(detail, list) and len(detail) == 1, r.text
    assert detail[0]["loc"] == ["body", "os_type"], r.text


@pytest.mark.parametrize("platform", PLATFORMS)
def test_create_takes_every_platform(test_client, db_session, admin_user, platform):
    headers = _headers(test_client)
    r = test_client.post(
        "/api/servers",
        json={"name": f"p-{platform}", "hostname": "h.example", "os_type": platform},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["osType"] == platform
    got = test_client.get(f"/api/servers/{r.json()['id']}", headers=headers)
    assert got.json()["osType"] == platform


def test_create_without_platform_stores_null(test_client, db_session, admin_user):
    r = test_client.post(
        "/api/servers",
        json={"name": "p-none", "hostname": "h.example"},
        headers=_headers(test_client),
    )
    assert r.status_code == 201, r.text
    assert r.json()["osType"] is None


@pytest.mark.parametrize("text", ["Ubuntu 24.04", "Linux", "win", "", "freebsd14"])
def test_create_refuses_free_text(test_client, db_session, admin_user, text):
    r = test_client.post(
        "/api/servers",
        json={"name": "p-free", "hostname": "h.example", "os_type": text},
        headers=_headers(test_client),
    )
    assert r.status_code == 422, (text, r.text)
    _assert_os_type_error(r)
    assert db_session.query(Server).count() == 0


def test_update_sets_clears_and_refuses(test_client, db_session, admin_user):
    headers = _headers(test_client)
    sid = test_client.post(
        "/api/servers",
        json={"name": "p-upd", "hostname": "h.example", "os_type": "linux"},
        headers=headers,
    ).json()["id"]

    r = test_client.put(f"/api/servers/{sid}", json={"os_type": "opnsense"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["osType"] == "opnsense"

    r = test_client.put(f"/api/servers/{sid}", json={"os_type": "Debian 13"}, headers=headers)
    assert r.status_code == 422, r.text
    _assert_os_type_error(r)
    db_session.expire_all()
    assert db_session.get(Server, sid).os_type == "opnsense"

    r = test_client.put(f"/api/servers/{sid}", json={"os_type": None}, headers=headers)
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.get(Server, sid).os_type is None
