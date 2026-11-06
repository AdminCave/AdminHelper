# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Who may set which connection options (R-1140). A read_write API key writes connections
(test_connections_authz.py), but the options that change where and with what the desktop opens
a session only a user login sets or changes. A key may send them back unchanged."""

import secrets

import pytest

from app.core.auth import hash_api_key
from app.modules.api_keys.models import ApiKey

GUARDED = {
    "ssh.agentForwarding": {"ssh": {"agentForwarding": True}},
    "ssh.forwards": {"ssh": {"forwards": [{"type": "D", "listen": "1080"}]}},
    "ssh.jumpHost": {"ssh": {"jumpHost": "bastion.example.org"}},
    "rdp.drives": {"rdp": {"drives": True}},
    "rdp.printers": {"rdp": {"printers": True}},
    "rdp.gateway": {"rdp": {"gateway": "rdgw.example.org:443"}},
    "rdp.nla": {"rdp": {"nla": False}},
}
# Options a key sets as before.
FREE = {"ssh": {"compression": True, "keepalive": 30}, "rdp": {"nla": True, "audio": "off"}}


def _key(db) -> dict:
    raw = f"ah_{secrets.token_urlsafe(16)}"
    db.add(ApiKey(name="k-rw", hashed_key=hash_api_key(raw), permission="read_write"))
    db.commit()
    return {"X-API-Key": raw}


def _admin(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create(client, h, options=None):
    body = {"name": "c", "kind": "ssh"}
    if options is not None:
        body["options"] = options
    return client.post("/api/connections", json=body, headers=h)


@pytest.mark.parametrize("name", sorted(GUARDED))
def test_a_key_may_not_create_a_connection_with_a_guarded_option(test_client, db_session, name):
    r = _create(test_client, _key(db_session), GUARDED[name])
    assert r.status_code == 403, r.text
    assert name in r.json()["detail"]


@pytest.mark.parametrize("name", sorted(GUARDED))
def test_a_key_may_not_change_a_guarded_option(test_client, db_session, admin_user, name):
    cid = _create(test_client, _admin(test_client)).json()["id"]
    r = test_client.put(
        f"/api/connections/{cid}", json={"options": GUARDED[name]}, headers=_key(db_session)
    )
    assert r.status_code == 403, r.text
    assert name in r.json()["detail"]


@pytest.mark.parametrize("name", sorted(GUARDED))
def test_an_admin_login_sets_every_guarded_option(test_client, db_session, admin_user, name):
    r = _create(test_client, _admin(test_client), GUARDED[name])
    assert r.status_code == 201, r.text
    assert r.json()["options"] == GUARDED[name]


def test_a_key_sets_the_other_options(test_client, db_session):
    h = _key(db_session)
    r = _create(test_client, h, FREE)
    assert r.status_code == 201, r.text
    r = test_client.put(
        f"/api/connections/{r.json()['id']}",
        json={"options": {"ssh": {"compression": False}}},
        headers=h,
    )
    assert r.status_code == 200, r.text


def test_a_key_writes_back_guarded_options_unchanged(test_client, db_session, admin_user):
    every = {
        "ssh": {
            **GUARDED["ssh.jumpHost"]["ssh"],
            "agentForwarding": True,
            "forwards": [
                {"type": "L", "listen": "8080", "target": "intranet.local:80"},
                {"type": "D", "listen": "*:1080"},
            ],
        },
        "rdp": {"drives": True, "printers": False, "gateway": "rdgw.example.org", "nla": False},
    }
    cid = _create(test_client, _admin(test_client), every).json()["id"]
    h = _key(db_session)
    shown = next(c for c in test_client.get("/api/connections", headers=h).json() if c["id"] == cid)
    # The other options and fields change; the guarded ones go back as they were read.
    shown["options"]["ssh"]["compression"] = True
    r = test_client.put(
        f"/api/connections/{cid}",
        json={"notes": "n", "options": shown["options"]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["options"]["ssh"]["jumpHost"] == "bastion.example.org"


@pytest.mark.parametrize(
    "options",
    [None, {}, {"rdp": {"audio": "off"}}],
    ids=["null", "empty", "other-only"],
)
def test_a_key_may_not_clear_a_guarded_option(test_client, db_session, admin_user, options):
    cid = _create(test_client, _admin(test_client), GUARDED["ssh.jumpHost"]).json()["id"]
    r = test_client.put(
        f"/api/connections/{cid}", json={"options": options}, headers=_key(db_session)
    )
    assert r.status_code == 403, r.text
    assert "ssh.jumpHost" in r.json()["detail"]


@pytest.mark.parametrize("before", [True, None], ids=["nla-on", "nla-default"])
def test_of_nla_only_false_is_guarded(test_client, db_session, admin_user, before):
    rdp = {} if before is None else {"nla": before}
    cid = _create(test_client, _admin(test_client), {"rdp": {**rdp, "audio": "off"}}).json()["id"]
    h = _key(db_session)
    on = test_client.put(
        f"/api/connections/{cid}", json={"options": {"rdp": {"nla": True}}}, headers=h
    )
    assert on.status_code == 200, on.text
    off = test_client.put(
        f"/api/connections/{cid}", json={"options": {"rdp": {"nla": False}}}, headers=h
    )
    assert off.status_code == 403, off.text


def test_a_key_may_turn_nla_back_on(test_client, db_session, admin_user):
    cid = _create(test_client, _admin(test_client), GUARDED["rdp.nla"]).json()["id"]
    h = _key(db_session)
    kept = test_client.put(
        f"/api/connections/{cid}", json={"options": GUARDED["rdp.nla"]}, headers=h
    )
    assert kept.status_code == 200, kept.text
    on = test_client.put(
        f"/api/connections/{cid}", json={"options": {"rdp": {"nla": True}}}, headers=h
    )
    assert on.status_code == 200, on.text
    assert on.json()["options"] == {"rdp": {"nla": True}}


def test_a_key_edits_the_other_fields_without_options(test_client, db_session, admin_user):
    body = {"name": "c", "kind": "ssh", "host": "a.example.org", "port": 22}
    body["options"] = GUARDED["ssh.jumpHost"]
    cid = test_client.post("/api/connections", json=body, headers=_admin(test_client)).json()["id"]
    # The same target sent back unchanged is no move.
    r = test_client.put(
        f"/api/connections/{cid}",
        json={"notes": "n", "host": "a.example.org", "port": 22, "kind": "ssh"},
        headers=_key(db_session),
    )
    assert r.status_code == 200, r.text
    assert r.json()["options"] == GUARDED["ssh.jumpHost"]


@pytest.mark.parametrize(
    "move",
    [{"host": "b.example.org"}, {"port": 2222}, {"kind": "rdp"}],
    ids=["host", "port", "kind"],
)
@pytest.mark.parametrize("name", sorted(GUARDED))
def test_a_key_may_not_move_a_connection_with_a_guarded_option(
    test_client, db_session, admin_user, name, move
):
    body = {"name": "c", "kind": "ssh", "host": "a.example.org", "port": 22}
    body["options"] = GUARDED[name]
    cid = test_client.post("/api/connections", json=body, headers=_admin(test_client)).json()["id"]
    r = test_client.put(f"/api/connections/{cid}", json=move, headers=_key(db_session))
    assert r.status_code == 403, r.text
    assert name in r.json()["detail"]
    assert next(iter(move)) in r.json()["detail"]


def test_a_key_moves_a_connection_without_guarded_options(test_client, db_session, admin_user):
    body = {"name": "c", "kind": "ssh", "host": "a.example.org", "options": FREE}
    cid = test_client.post("/api/connections", json=body, headers=_admin(test_client)).json()["id"]
    r = test_client.put(
        f"/api/connections/{cid}",
        json={"host": "b.example.org", "port": 2222},
        headers=_key(db_session),
    )
    assert r.status_code == 200, r.text
