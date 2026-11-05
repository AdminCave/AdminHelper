# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-connection options (R-1066). The desktop turns them into ssh and FreeRDP arguments, so
the API is the first boundary: every free-form value has a strict format, unknown keys are
refused, and only the fields set are stored (a field left out means the global default)."""

import json

import pytest

from app.modules.connections.models import Connection

FULL = {
    "ssh": {
        "jumpHost": "ops@bastion.example.org:2222,[2001:db8::1]",
        "forwards": [
            {"type": "L", "listen": "8080", "target": "intranet.local:80"},
            {"type": "R", "listen": "127.0.0.1:9000", "target": "[::1]:9000"},
            {"type": "D", "listen": "*:1080"},
        ],
        "agentForwarding": True,
        "compression": False,
        "keepalive": 30,
        "authMethod": "agent",
    },
    "rdp": {
        "scalingMode": "hdpi",
        "windowMode": "custom",
        "customSize": "1920x1080",
        "performanceProfile": "lan",
        "drives": True,
        "audio": "remote",
        "printers": False,
        "gateway": "rdgw.example.org:443",
        "nla": True,
    },
}


def _login(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create(client, h, **fields):
    return client.post("/api/connections", json={"name": "c", "kind": "ssh", **fields}, headers=h)


def test_options_round_trip_through_create_list_and_export(test_client, db_session, admin_user):
    h = _login(test_client)

    r = _create(test_client, h, options=FULL)

    assert r.status_code == 201, r.text
    assert r.json()["options"] == FULL
    listed = test_client.get("/api/connections", headers=h).json()
    assert [c["options"] for c in listed] == [FULL]
    exported = json.loads(test_client.get("/api/connections/export", headers=h).content)
    assert [c["options"] for c in exported] == [FULL]
    # A column of its own, not an extra field.
    row = db_session.query(Connection).one()
    assert json.loads(row.options) == FULL
    assert row.extra_data is None


def test_only_the_fields_set_are_stored(test_client, db_session, admin_user):
    h = _login(test_client)

    r = _create(test_client, h, options={"ssh": {"compression": False}, "rdp": {}})

    assert r.status_code == 201, r.text
    assert r.json()["options"] == {"ssh": {"compression": False}}
    assert db_session.query(Connection).one().options == '{"ssh": {"compression": false}}'


@pytest.mark.parametrize("options", [None, {}, {"ssh": {}, "rdp": {}}, {"ssh": {"forwards": []}}])
def test_empty_options_store_nothing_and_answer_none(test_client, db_session, admin_user, options):
    h = _login(test_client)

    r = _create(test_client, h, options=options)

    assert r.status_code == 201, r.text
    assert "options" not in r.json()
    assert db_session.query(Connection).one().options is None


def test_update_replaces_the_options_and_null_clears_them(test_client, db_session, admin_user):
    h = _login(test_client)
    cid = _create(test_client, h, options=FULL).json()["id"]

    r = test_client.put(
        f"/api/connections/{cid}", json={"options": {"rdp": {"nla": False}}}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["options"] == {"rdp": {"nla": False}}

    # An update that does not name options keeps them.
    r = test_client.put(f"/api/connections/{cid}", json={"notes": "n"}, headers=h)
    assert r.json()["options"] == {"rdp": {"nla": False}}

    r = test_client.put(f"/api/connections/{cid}", json={"options": None}, headers=h)
    assert r.status_code == 200, r.text
    assert "options" not in r.json()
    db_session.expire_all()
    assert db_session.query(Connection).one().options is None


BAD = [
    # leading dash: ssh would read it as an option
    ({"ssh": {"jumpHost": "-oProxyCommand=touch /tmp/x"}}, ("ssh", "jumpHost")),
    ({"ssh": {"jumpHost": "user@-host"}}, ("ssh", "jumpHost")),
    ({"ssh": {"jumpHost": "host;id"}}, ("ssh", "jumpHost")),
    ({"ssh": {"jumpHost": "host name"}}, ("ssh", "jumpHost")),
    ({"ssh": {"jumpHost": "host\n-oX"}}, ("ssh", "jumpHost")),
    ({"ssh": {"jumpHost": "host\x01"}}, ("ssh", "jumpHost")),
    ({"ssh": {"jumpHost": "host:0"}}, ("ssh", "jumpHost")),
    ({"ssh": {"jumpHost": "host:65536"}}, ("ssh", "jumpHost")),
    ({"ssh": {"jumpHost": ""}}, ("ssh", "jumpHost")),
    ({"ssh": {"jumpHost": ",".join(["h"] * 9)}}, ("ssh", "jumpHost")),
    ({"ssh": {"forwards": [{"type": "L", "listen": "0", "target": "h:1"}]}}, ("ssh", "forwards")),
    (
        {"ssh": {"forwards": [{"type": "L", "listen": "-1", "target": "h:1"}]}},
        ("ssh", "forwards"),
    ),
    (
        {"ssh": {"forwards": [{"type": "L", "listen": "80", "target": "-oX=y:1"}]}},
        ("ssh", "forwards"),
    ),
    (
        {"ssh": {"forwards": [{"type": "L", "listen": "80", "target": "h:1 -oX=y"}]}},
        ("ssh", "forwards"),
    ),
    ({"ssh": {"forwards": [{"type": "L", "listen": "80"}]}}, ("ssh", "forwards")),
    (
        {"ssh": {"forwards": [{"type": "D", "listen": "1080", "target": "h:1"}]}},
        ("ssh", "forwards"),
    ),
    ({"ssh": {"forwards": [{"type": "X", "listen": "80"}]}}, ("ssh", "forwards")),
    (
        {"ssh": {"forwards": [{"type": "D", "listen": "1080", "extra": 1}]}},
        ("ssh", "forwards"),
    ),
    ({"ssh": {"keepalive": 0}}, ("ssh", "keepalive")),
    ({"ssh": {"keepalive": 3601}}, ("ssh", "keepalive")),
    ({"ssh": {"authMethod": "keyboard-interactive"}}, ("ssh", "authMethod")),
    ({"ssh": {"proxyCommand": "nc %h %p"}}, ("ssh", "proxyCommand")),
    ({"rdp": {"gateway": "-gw"}}, ("rdp", "gateway")),
    ({"rdp": {"gateway": "gw /u:admin"}}, ("rdp", "gateway")),
    ({"rdp": {"customSize": "100x100"}}, ("rdp", "customSize")),
    ({"rdp": {"customSize": "1920x1080x60"}}, ("rdp", "customSize")),
    ({"rdp": {"scalingMode": "zoom"}}, ("rdp", "scalingMode")),
    ({"rdp": {"audio": "loud"}}, ("rdp", "audio")),
    ({"rdp": {"drive": "/"}}, ("rdp", "drive")),
    ({"vnc": {}}, ("vnc",)),
]


@pytest.mark.parametrize(("options", "loc"), BAD)
def test_bad_options_are_refused_at_their_location(
    test_client, db_session, admin_user, options, loc
):
    h = _login(test_client)

    r = _create(test_client, h, options=options)

    assert r.status_code == 422, r.text
    locs = [tuple(e["loc"]) for e in r.json()["detail"]]
    assert any(item[: 2 + len(loc)] == ("body", "options", *loc) for item in locs), locs
    assert db_session.query(Connection).count() == 0


@pytest.mark.parametrize(("options", "loc"), BAD[:3] + BAD[-4:])
def test_bad_options_are_refused_on_update(test_client, db_session, admin_user, options, loc):
    h = _login(test_client)
    cid = _create(test_client, h, options={"rdp": {"nla": True}}).json()["id"]

    r = test_client.put(f"/api/connections/{cid}", json={"options": options}, headers=h)

    assert r.status_code == 422, r.text
    db_session.expire_all()
    assert json.loads(db_session.query(Connection).one().options) == {"rdp": {"nla": True}}


def test_import_checks_the_options_of_every_entry(test_client, db_session, admin_user):
    h = _login(test_client)
    body = {
        "mode": "merge",
        "connections": [
            {"name": "ok", "kind": "ssh", "options": FULL},
            {"name": "bad", "kind": "ssh", "options": {"ssh": {"jumpHost": "-oX"}}},
        ],
    }

    r = test_client.post("/api/connections/import", json=body, headers=h)

    assert r.status_code == 422, r.text
    assert [e["loc"][:4] for e in r.json()["detail"]] == [["body", "connections", 1, "options"]]
    assert db_session.query(Connection).count() == 0

    body["connections"].pop()
    r = test_client.post("/api/connections/import", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert json.loads(db_session.query(Connection).one().options) == FULL


@pytest.mark.parametrize("stored", ["not json", "[1, 2]", "null"])
def test_a_row_with_unreadable_options_still_lists(test_client, db_session, admin_user, stored):
    db_session.add(Connection(id="c1", name="c1", kind="ssh", options=stored))
    db_session.commit()
    h = _login(test_client)

    r = test_client.get("/api/connections", headers=h)

    assert r.status_code == 200, r.text
    assert "options" not in r.json()[0]


def test_an_extra_field_named_like_a_known_one_does_not_leak(test_client, db_session, admin_user):
    """Rows from before the column could carry an extra entry "options"; the column wins."""
    db_session.add(
        Connection(id="c1", name="c1", kind="ssh", extra_data=json.dumps({"options": "x"}))
    )
    db_session.commit()
    h = _login(test_client)

    r = test_client.get("/api/connections", headers=h)

    assert "options" not in r.json()[0]
