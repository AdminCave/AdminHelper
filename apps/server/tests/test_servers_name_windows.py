# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1056: POST/PUT /api/servers refuse a new or renamed server name with ':' or a
Windows device name (the bulk-ZIP makes it a folder), while a name stored before the
rule stays valid: an edit that sends it back unchanged passes."""

from app.modules.servers.models import Server


def _headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_create_refuses_a_colon_and_a_device_name(test_client, db_session, admin_user):
    headers = _headers(test_client)
    for name in ("srv:1", "aux", "NUL.lab"):
        r = test_client.post(
            "/api/servers", json={"name": name, "hostname": "h.example"}, headers=headers
        )
        assert r.status_code == 422, (name, r.text)
        assert isinstance(r.json()["detail"], str)
    assert db_session.query(Server).count() == 0


def test_create_refuses_the_console_handle_names(test_client, db_session, admin_user):
    # Not named by Microsoft Learn; Python's ntpath.isreserved counts them (R-1176).
    headers = _headers(test_client)
    for name in ("CONIN$", "conout$", "conin$.lab"):
        r = test_client.post(
            "/api/servers", json={"name": name, "hostname": "h.example"}, headers=headers
        )
        assert r.status_code == 422, (name, r.text)
        assert isinstance(r.json()["detail"], str)
    assert db_session.query(Server).count() == 0


def test_create_keeps_allowing_other_names(test_client, db_session, admin_user):
    r = test_client.post(
        "/api/servers",
        json={"name": "console-01", "hostname": "h.example"},
        headers=_headers(test_client),
    )
    assert r.status_code == 201, r.text


def test_rename_to_a_device_name_is_refused(test_client, db_session, admin_user):
    headers = _headers(test_client)
    created = test_client.post(
        "/api/servers", json={"name": "web-1", "hostname": "h.example"}, headers=headers
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    r = test_client.put(f"/api/servers/{sid}", json={"name": "com3"}, headers=headers)
    assert r.status_code == 422, r.text
    db_session.expire_all()
    assert db_session.get(Server, sid).name == "web-1"


def test_rename_to_a_console_handle_name_is_refused(test_client, db_session, admin_user):
    headers = _headers(test_client)
    created = test_client.post(
        "/api/servers", json={"name": "web-2", "hostname": "h.example"}, headers=headers
    )
    assert created.status_code == 201, created.text
    r = test_client.put(
        f"/api/servers/{created.json()['id']}", json={"name": "CONOUT$"}, headers=headers
    )
    assert r.status_code == 422, r.text


def test_a_stored_console_handle_name_stays_editable(test_client, db_session, admin_user):
    db_session.add(Server(id="legacy-conin", name="CONIN$", hostname="old.example"))
    db_session.commit()
    r = test_client.put(
        "/api/servers/legacy-conin",
        json={"name": "CONIN$", "hostname": "new.example"},
        headers=_headers(test_client),
    )
    assert r.status_code == 200, r.text


def test_a_stored_name_from_before_stays_editable(test_client, db_session, admin_user):
    db_session.add(Server(id="legacy-aux", name="aux", hostname="old.example"))
    db_session.commit()
    headers = _headers(test_client)
    r = test_client.put(
        "/api/servers/legacy-aux",
        json={"name": "aux", "hostname": "new.example"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "aux"
    assert r.json()["hostname"] == "new.example"
    # Renaming away from it is fine; renaming back is a new name and refused.
    assert (
        test_client.put(
            "/api/servers/legacy-aux", json={"name": "aux-host"}, headers=headers
        ).status_code
        == 200
    )
    r = test_client.put("/api/servers/legacy-aux", json={"name": "aux"}, headers=headers)
    assert r.status_code == 422, r.text
