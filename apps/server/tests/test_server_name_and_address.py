# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1210 (Kevin 2026-11-09, 2a and 5a): a server has one name, entered once. Its address
follows the name unless an own hostname (an IP, an internal name) is stored; the API hands
out the address as `hostname` and says with `customHostname` whether it is an own one. A new
or changed name must not be another server's name, case aside; names stored twice before
stay, and an edit that keeps the name passes."""

import json

import pytest

from app.modules.servers.models import Server
from app.modules.servers.schemas import stored_hostname


def _headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create(client, headers, **body):
    r = client.post("/api/servers", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize(
    ("hostname", "stored"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("web01.kunde.example", None),
        (" WEB01.Kunde.Example ", None),
        ("192.0.2.10", "192.0.2.10"),
        (" web01.intern.example ", "web01.intern.example"),
    ],
)
def test_stored_hostname_keeps_only_an_own_address(hostname, stored):
    assert stored_hostname("web01.kunde.example", hostname) == stored


def test_a_server_created_with_its_name_only_is_reached_at_its_name(
    test_client, db_session, admin_user
):
    created = _create(test_client, _headers(test_client), name="web01.kunde.example")
    assert (created["hostname"], created["customHostname"]) == ("web01.kunde.example", False)
    assert db_session.get(Server, created["id"]).hostname is None


def test_an_older_client_sending_the_name_as_hostname_sets_no_own_address(
    test_client, db_session, admin_user
):
    created = _create(
        test_client,
        _headers(test_client),
        name="web01.kunde.example",
        hostname="Web01.Kunde.Example",
    )
    assert created["customHostname"] is False
    assert db_session.get(Server, created["id"]).hostname is None


def test_an_own_address_stays_and_a_blank_one_follows_the_name_again(
    test_client, db_session, admin_user
):
    headers = _headers(test_client)
    created = _create(test_client, headers, name="mail.kunde.example", hostname="192.0.2.10")
    assert (created["hostname"], created["customHostname"]) == ("192.0.2.10", True)

    r = test_client.put(f"/api/servers/{created['id']}", json={"hostname": ""}, headers=headers)
    assert r.status_code == 200, r.text
    assert (r.json()["hostname"], r.json()["customHostname"]) == ("mail.kunde.example", False)


def test_a_rename_takes_the_address_along(test_client, db_session, admin_user):
    headers = _headers(test_client)
    created = _create(test_client, headers, name="web01.kunde.example")
    r = test_client.put(
        f"/api/servers/{created['id']}", json={"name": "web02.kunde.example"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert (r.json()["hostname"], r.json()["customHostname"]) == ("web02.kunde.example", False)


def test_an_older_client_renaming_with_the_old_name_as_hostname_keeps_it_following(
    test_client, db_session, admin_user
):
    # A client from before R-1210 sends every field back, `hostname` being the address it
    # was shown: the old name.
    headers = _headers(test_client)
    created = _create(test_client, headers, name="web01.kunde.example")
    r = test_client.put(
        f"/api/servers/{created['id']}",
        json={"name": "web02.kunde.example", "hostname": "web01.kunde.example"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert (r.json()["hostname"], r.json()["customHostname"]) == ("web02.kunde.example", False)


def test_a_null_name_is_refused_not_a_500(test_client, db_session, admin_user):
    headers = _headers(test_client)
    created = _create(test_client, headers, name="web01.kunde.example")
    r = test_client.put(f"/api/servers/{created['id']}", json={"name": None}, headers=headers)
    assert r.status_code == 422, r.text
    db_session.expire_all()
    assert db_session.get(Server, created["id"]).name == "web01.kunde.example"


def test_a_rename_to_the_own_address_makes_it_follow_the_name(test_client, db_session, admin_user):
    headers = _headers(test_client)
    created = _create(test_client, headers, name="web01", hostname="web01.kunde.example")
    r = test_client.put(
        f"/api/servers/{created['id']}", json={"name": "web01.kunde.example"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["customHostname"] is False
    db_session.expire_all()
    assert db_session.get(Server, created["id"]).hostname is None


def test_a_taken_name_is_refused_case_aside(test_client, db_session, admin_user):
    headers = _headers(test_client)
    first = _create(test_client, headers, name="web01.kunde.example")
    other = _create(test_client, headers, name="db01.kunde.example")

    r = test_client.post("/api/servers", json={"name": "WEB01.kunde.example"}, headers=headers)
    assert r.status_code == 409, r.text
    r = test_client.put(
        f"/api/servers/{other['id']}", json={"name": "Web01.Kunde.Example"}, headers=headers
    )
    assert r.status_code == 409, r.text
    db_session.expire_all()
    assert db_session.get(Server, other["id"]).name == "db01.kunde.example"
    # The server itself may change the case of its own name.
    r = test_client.put(
        f"/api/servers/{first['id']}", json={"name": "Web01.kunde.example"}, headers=headers
    )
    assert r.status_code == 200, r.text


def test_names_stored_twice_before_stay_editable(test_client, db_session, admin_user):
    db_session.add(Server(id="dup-1", name="web01", hostname="192.0.2.11"))
    db_session.add(Server(id="dup-2", name="web01", hostname="192.0.2.12"))
    db_session.commit()
    r = test_client.put(
        "/api/servers/dup-2",
        json={"name": "web01", "notes": "second box"},
        headers=_headers(test_client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["hostname"] == "192.0.2.12"


def test_every_listing_hands_out_the_address(test_client, db_session, admin_user, monkeypatch):
    import app.modules.notifications.router as notifications_router

    db_session.add(Server(id="s-own", name="mail", hostname="192.0.2.10", tags=json.dumps([])))
    db_session.add(Server(id="s-name", name="web01.kunde.example", hostname=None))
    db_session.commit()
    admin_user.servers.extend([db_session.get(Server, "s-own"), db_session.get(Server, "s-name")])
    db_session.commit()
    headers = _headers(test_client)
    expected = {"s-own": "192.0.2.10", "s-name": "web01.kunde.example"}

    listed = test_client.get("/api/servers", headers=headers).json()
    assert {s["id"]: s["hostname"] for s in listed} == expected
    summary = test_client.get("/api/servers/summary", headers=headers).json()
    assert {s["id"]: s["hostname"] for s in summary} == expected
    mine = test_client.get("/api/users/me/servers", headers=headers).json()
    assert {s["id"]: s["hostname"] for s in mine} == expected
    monkeypatch.setattr(notifications_router, "MONITOR_API_KEY", "internal-test-key")
    internal = test_client.get(
        "/api/internal/servers", headers={"X-Internal-Key": "internal-test-key"}
    ).json()
    assert {s["id"]: s["hostname"] for s in internal} == expected
