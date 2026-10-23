# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""NUL bytes are refused at the edge, not by the driver (T7).

Postgres stores no 0x00 in a text value. Until this change the byte travelled
all the way into psycopg, which raised DataError while binding the parameter —
uncaught, before any response existed, so the client saw HTTP 500. Reproduced
2026-09-22 on all seven sites below, and recorded before that in
tests/schemathesis_exclude.toml for POST /api/enrollment/token/for and
GET /api/audit. POST /api/hooks came out of the fuzz run of the same day, once
those exclusions were off and not_a_server_error could see the route again.

The bound is deliberately only the NUL byte: every other control character is
storable, and the TOML-injection guards in frp/schemas.py are a separate
concern.

A lone surrogate (U+D800 to U+DFFF, on the wire only as a JSON escape) is
refused the same way, at the end of this file: it has no UTF-8 form, so psycopg
could not bind it to a text column (500), and in tags json.dumps stored it as
an escape, after which every answer carrying the row was a 500."""

import json

import pytest

from app.modules.connections.models import Connection
from app.modules.frp.models import FrpTunnel
from tests.test_frp_tunnels import _body as _tunnel_body
from tests.test_frp_tunnels import _seed as _seed_tunnel
from tests.test_validation_response import _strict_loads

NUL = chr(0)
LONE = "\ud800"
AUDIT_FILTERS = ("action", "actor_type", "object_type", "object_id", "status", "q")


def _login(test_client) -> dict:
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.parametrize("field", AUDIT_FILTERS)
def test_audit_filters_reject_a_nul_byte(field, test_client, db_session, admin_user):
    headers = _login(test_client)

    ok = test_client.get("/api/audit", params={field: "plain"}, headers=headers)
    assert ok.status_code == 200, f"{field}: {ok.status_code} {ok.text}"

    nul = test_client.get("/api/audit", params={field: "a" + NUL + "b"}, headers=headers)
    assert nul.status_code == 422, f"{field}: {nul.status_code} {nul.text}"


def test_enrollment_token_for_rejects_a_nul_username(test_client, db_session, admin_user):
    headers = _login(test_client)

    # A username that does not exist answers 404 — the value reached the lookup.
    ok = test_client.post("/api/enrollment/token/for", json={"username": "ghost"}, headers=headers)
    assert ok.status_code == 404, ok.text

    nul = test_client.post(
        "/api/enrollment/token/for", json={"username": "a" + NUL + "b"}, headers=headers
    )
    assert nul.status_code == 422, nul.text
    assert nul.json()["detail"][0]["loc"][-1] == "username"


def test_hook_script_rejects_a_nul_byte(test_client, db_session, admin_user):
    """Found by the fuzzer, not by reading: with the old exclusions gone,
    POST /api/hooks with a NUL in `script` died in the INSERT (T10)."""
    headers = _login(test_client)

    ok = test_client.post(
        "/api/hooks",
        json={"name": "h1", "hook_type": "webhook", "script": "result = {}"},
        headers=headers,
    )
    assert ok.status_code == 201, ok.text

    nul = test_client.post(
        "/api/hooks",
        json={"name": "h2", "hook_type": "webhook", "script": NUL},
        headers=headers,
    )
    assert nul.status_code == 422, nul.text
    assert nul.json()["detail"][0]["loc"][-1] == "script"


def test_user_server_ids_reject_a_nul_byte(test_client, db_session, admin_user):
    """server_ids carries no numeric bound — servers.id is a String column — but a
    NUL in one of them reached Server.id.in_() and died in the driver (found by
    the fuzzer on POST /api/users, 2026-09-22)."""
    headers = _login(test_client)
    body = {"username": "newuser", "password": "supersecret1", "server_ids": ["srv-a"]}

    ok = test_client.post("/api/users", json=body, headers=headers)
    assert ok.status_code == 201, ok.text

    nul = test_client.post(
        "/api/users",
        json={**body, "username": "other", "server_ids": ["srv-a", "b" + NUL]},
        headers=headers,
    )
    assert nul.status_code == 422, nul.text
    assert nul.json()["detail"][0]["loc"][-2] == "server_ids"


def test_internal_event_fields_reject_a_nul_byte(test_client, db_session, admin_user, monkeypatch):
    """Found by the fuzzer on `source_id` (2026-09-22): every text field of an
    incoming event is written verbatim into a Notification row, and source_id is
    compared against Server.id on the way."""
    monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
    headers = {"X-Internal-Key": "secret"}
    payload = {
        "event_type": "monitoring.check.transition",
        "severity": "critical",
        "category": "monitoring",
        "title": "CPU critical on web01",
        "source_type": "server",
        "source_id": "srv-1",
    }

    ok = test_client.post("/api/internal/events", json=payload, headers=headers)
    assert ok.status_code == 202, ok.text

    for field in (
        "event_type",
        "category",
        "title",
        "body",
        "source_type",
        "source_id",
        "new_status",
    ):
        r = test_client.post(
            "/api/internal/events", json={**payload, field: "a" + NUL}, headers=headers
        )
        assert r.status_code == 422, f"{field}: {r.status_code} {r.text}"
        assert r.json()["detail"][0]["loc"][-1] == field

    # A bundled event's ids go into Server.id.in_() just like source_id.
    bundle = {key: value for key, value in payload.items() if key != "source_id"}
    ok = test_client.post(
        "/api/internal/events", json={**bundle, "source_ids": ["srv-1", "srv-2"]}, headers=headers
    )
    assert ok.status_code == 202, ok.text

    nul = test_client.post(
        "/api/internal/events", json={**bundle, "source_ids": ["srv-1", "b" + NUL]}, headers=headers
    )
    assert nul.status_code == 422, nul.text
    assert nul.json()["detail"][0]["loc"][-2:] == ["source_ids", 1]


def test_api_key_name_rejects_a_nul_byte(test_client, db_session, admin_user):
    """Found by the fuzzer while verifying an unrelated task (2026-09-23):
    ApiKeyCreate.name went into Column(String) unguarded, so a NUL died in the
    INSERT. The route was never under an exclusion — it only fails when
    Hypothesis happens to draw a NUL for the name."""
    headers = _login(test_client)

    ok = test_client.post(
        "/api/api-keys", json={"name": "k1", "permission": "read"}, headers=headers
    )
    assert ok.status_code == 201, ok.text

    nul = test_client.post(
        "/api/api-keys", json={"name": NUL, "permission": "read"}, headers=headers
    )
    assert nul.status_code == 422, nul.text
    assert nul.json()["detail"][0]["loc"][-1] == "name"


# --- a lone surrogate ---


def _send_lone(test_client, method: str, url: str, body: dict, headers: dict):
    # Only a JSON escape spells a lone surrogate on the wire; it has no UTF-8 form.
    content = json.dumps(body)
    assert "\\ud800" in content
    return test_client.request(
        method, url, content=content, headers={**headers, "Content-Type": "application/json"}
    )


def _refused_at(r, loc: list) -> None:
    """One 422 at `loc`, readable as any client reads it: strict UTF-8."""
    assert r.status_code == 422, r.text
    assert [error["loc"] for error in _strict_loads(r.content)["detail"]] == [loc], r.text


def _lists_stay_readable(test_client, headers: dict) -> tuple[list, list]:
    servers = test_client.get("/api/servers", headers=headers)
    assert servers.status_code == 200, servers.text
    connections = test_client.get("/api/connections", headers=headers)
    assert connections.status_code == 200, connections.text
    return servers.json(), connections.json()


# A text column each (psycopg could not bind the value) and a tag list (stored as an escape).
SERVER_FIELDS = [
    ("hostname", LONE, ["body", "hostname"]),
    ("notes", LONE, ["body", "notes"]),
    ("tags", ["ok", LONE], ["body", "tags", 1]),
]
TUNNEL_FIELDS = [
    ("protocol", LONE, ["body", "protocol"]),
    ("connection_id", LONE, ["body", "connection_id"]),
    ("tags", ["ok", LONE], ["body", "tags", 1]),
]


def test_server_fields_reject_a_lone_surrogate(test_client, db_session, admin_user):
    headers = _login(test_client)
    sent = {"name": "srv-a", "hostname": "a.example.test", "notes": "n", "tags": ["ok"]}
    created = test_client.post("/api/servers", json=sent, headers=headers)
    assert created.status_code == 201, created.text
    server_id = created.json()["id"]

    for field, value, loc in SERVER_FIELDS:
        body = {"name": "srv-b", "hostname": "b.example.test", field: value}
        _refused_at(_send_lone(test_client, "POST", "/api/servers", body, headers), loc)
        url = f"/api/servers/{server_id}"
        _refused_at(_send_lone(test_client, "PUT", url, {field: value}, headers), loc)

    servers, _ = _lists_stay_readable(test_client, headers)
    assert [{key: s[key] for key in ("id", *sent)} for s in servers] == [{"id": server_id, **sent}]


def test_tunnel_fields_reject_a_lone_surrogate(test_client, db_session, admin_user):
    _seed_tunnel(db_session)
    headers = _login(test_client)

    for field, value, loc in TUNNEL_FIELDS:
        body = _tunnel_body(**{field: value})
        _refused_at(_send_lone(test_client, "POST", "/api/frp/tunnels", body, headers), loc)
        url = "/api/frp/tunnels/t-a"
        _refused_at(_send_lone(test_client, "PUT", url, {field: value}, headers), loc)

    db_session.expire_all()
    stored = db_session.query(FrpTunnel).one()
    assert (stored.id, stored.protocol, stored.connection_id, stored.tags) == (
        "t-a",
        "ssh",
        None,
        None,
    )
    servers, _ = _lists_stay_readable(test_client, headers)
    assert [t["id"] for s in servers for t in s["frpTunnels"]] == ["t-a"]


def test_connection_tags_reject_a_lone_surrogate(test_client, db_session, admin_user):
    headers = _login(test_client)
    body = {"name": "c1", "kind": "ssh", "host": "c1.example.test", "tags": ["ok", LONE]}
    _refused_at(
        _send_lone(test_client, "POST", "/api/connections", body, headers), ["body", "tags", 1]
    )

    servers, connections = _lists_stay_readable(test_client, headers)
    assert (servers, connections) == ([], [])
    assert db_session.query(Connection).count() == 0
