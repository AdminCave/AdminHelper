# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A NUL byte is refused at the monitoring edge: path, query, body, agent report.
So is a lone surrogate in a body or an agent report.

This suite runs on sqlite, which stores a NUL without complaint — here the
unguarded requests answer 2xx or 404, not 500, and it is the 422 assertions that
go red without the guards. In production the database is Postgres, where the
same requests died in the driver."""

import json

import pytest
from pydantic import BaseModel

from app.core.bounds import RequestModel

NUL = chr(0)

_CHECK = {"name": "c1", "check_type": "ping", "config": {"target": "h1"}, "enabled": False}


def test_a_nul_in_the_path_is_422_before_routing(client_db):
    client, _ = client_db
    assert client.get("/checks/ghost").status_code == 404
    r = client.get("/checks/a%00b")
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["path"]
    # No route matches this one: a 404 would mean the request reached routing.
    assert client.get("/no-such-route/a%00b").status_code == 422


def test_a_nul_in_a_query_value_is_422(client_db):
    client, _ = client_db
    assert client.get("/checks", params={"server_id": "ghost"}).status_code == 200
    r = client.get("/checks", params={"server_id": "a" + NUL + "b"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["query", "server_id"]


def test_a_nul_in_a_query_name_is_422(client_db):
    client, _ = client_db
    r = client.get("/checks", params={"a" + NUL: "1"})
    assert r.status_code == 422, r.text
    # The name is the input at fault here, not the value that follows it.
    assert r.json()["detail"][0]["loc"] == ["query", "a" + NUL]
    assert r.json()["detail"][0]["input"] == "a" + NUL


def test_an_encoded_percent_sign_is_not_a_nul(client_db):
    # `%2500` decodes once, to the three characters "%00"; the guard must not
    # decode a second time. Query only: Starlette's TestClient decodes a PATH
    # twice by itself, so a path case would test the client, not the guard.
    client, _ = client_db
    assert client.get("/checks?server_id=a%2500b").status_code == 200


@pytest.mark.parametrize("field", ["name", "description", "server_id"])
def test_a_nul_in_a_body_field_is_422(field, client_db):
    client, _ = client_db
    assert client.post("/checks", json=_CHECK).status_code == 201
    r = client.post("/checks", json={**_CHECK, field: "a" + NUL + "b"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["body", field]


def test_a_nul_in_the_agent_report_is_422_but_liveness_counts(client_db, monkeypatch, caplog):
    """The report is a plain dict, not a model — its shape belongs to the agent — so
    the handler checks it, after recording liveness: a refused report must not
    turn into a "server down" alarm from agent_ping (Kevin, 2026-09-23)."""
    from app.checkers import agent as agent_checker
    from app.models import MonitorAgentLiveness

    client, factory = client_db
    report = {"systemd": {"failed": ["sshd.service"]}}
    assert client.post("/agent/srv-1/report", json=report).status_code == 200

    monkeypatch.setattr(agent_checker, "_last_report", {})
    with factory() as db:
        db.query(MonitorAgentLiveness).delete()
        db.commit()
    bad = {"systemd": {"failed": ["a" + NUL + ".service"]}}
    with caplog.at_level("WARNING"):
        r = client.post("/agent/srv-1/report", json=bad)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["body", "systemd", "failed", 0]
    # Liveness was recorded all the same, in memory and in its table.
    assert "srv-1" in agent_checker._last_report
    with factory() as db:
        assert db.get(MonitorAgentLiveness, "srv-1") is not None
    # And someone can see why this server's checks stand still.
    assert any("srv-1" in m and "systemd" in m for m in caplog.messages), caplog.messages


# A lone surrogate (U+D800 to U+DFFF) has no UTF-8 form. JSON spells one only as an
# escape, so the bodies below go out as JSON text: json.dumps writes the escape, httpx's
# json= would have to encode the character and cannot.
_JSON = {"content-type": "application/json"}
_SURROGATE_MSG = "Value error, must not contain a lone surrogate (U+D800 to U+DFFF)"


def test_a_lone_surrogate_in_a_body_field_is_422(client_db):
    client, _ = client_db
    r = client.post("/checks", content=json.dumps({**_CHECK, "name": "a\ud800"}), headers=_JSON)
    assert r.status_code == 422, r.text
    [error] = r.json()["detail"]
    assert (error["loc"], error["msg"], error["input"]) == (
        ["body", "name"],
        _SURROGATE_MSG,
        "a\ud800",
    )


@pytest.mark.parametrize(
    ("check_type", "config", "field"),
    [
        ("ping", {"target": "h\ud800"}, "target"),
        ("http", {"url": "https://web.example/", "search_string": "a\ud800"}, "search_string"),
    ],
)
def test_a_lone_surrogate_in_the_config_is_422_and_nothing_is_stored(
    client_db, check_type, config, field
):
    # config is stored as json.dumps text, which escapes the surrogate: a search_string
    # went into the row that way, and every later answer carrying it could not be encoded.
    client, _ = client_db
    body = {**_CHECK, "check_type": check_type, "config": config}
    r = client.post("/checks", content=json.dumps(body), headers=_JSON)
    assert r.status_code == 422, r.text
    [error] = r.json()["detail"]
    assert (error["loc"], error["msg"]) == (["body", "config", field], _SURROGATE_MSG)
    r = client.get("/checks")
    assert (r.status_code, r.json()) == (200, [])


def test_a_lone_surrogate_in_a_key_is_422_at_the_key(client_db):
    client, _ = client_db
    body = {**_CHECK, "config": {"target": "h1", "k\udfff": 1}}
    r = client.post("/checks", content=json.dumps(body), headers=_JSON)
    assert r.status_code == 422, r.text
    [error] = r.json()["detail"]
    # pydantic-core holds a loc as UTF-8, so the key comes back with U+FFFD for each byte
    # of its surrogatepass form, as Python's own "replace" decoder writes it; the input
    # is the key itself.
    key = "k\udfff".encode("utf-8", "surrogatepass").decode("utf-8", "replace")
    assert (error["loc"], error["msg"], error["input"]) == (
        ["body", "config", key],
        _SURROGATE_MSG,
        "k\udfff",
    )


def test_a_paired_surrogate_is_one_character_and_passes(client_db):
    # JSON spells U+1F600 as the escape pair \ud83d\ude00; json.loads joins it.
    client, _ = client_db
    body = json.dumps({**_CHECK, "name": "\U0001f600"})
    assert "\\ud83d\\ude00" in body
    r = client.post("/checks", content=body, headers=_JSON)
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "\U0001f600"


def test_a_lone_surrogate_in_the_agent_report_is_422_but_liveness_counts(
    client_db, monkeypatch, caplog
):
    """As a tag value the surrogate failed to encode in VictoriaClient._send, and the
    whole batch went with it, lines of other servers included."""
    from app.checkers import agent as agent_checker
    from app.core import victoria as victoria_mod
    from app.models import MonitorAgentLiveness

    client, factory = client_db
    writes = []
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: writes.append(lines))
    monkeypatch.setattr(agent_checker, "_last_report", {})
    bad = {"resources": {"disks": [{"mount": "\ud800", "fstype": "ext4", "percent": 5}]}}
    with caplog.at_level("WARNING"):
        r = client.post("/agent/srv-1/report", content=json.dumps(bad), headers=_JSON)
    assert r.status_code == 422, r.text
    [error] = r.json()["detail"]
    assert (error["loc"], error["msg"]) == (
        ["body", "resources", "disks", 0, "mount"],
        _SURROGATE_MSG,
    )
    assert writes == []
    assert "srv-1" in agent_checker._last_report
    with factory() as db:
        assert db.get(MonitorAgentLiveness, "srv-1") is not None
    assert any("srv-1" in m and "lone surrogate" in m and "disks" in m for m in caplog.messages), (
        caplog.messages
    )


def _refs(node) -> set[str]:
    if isinstance(node, dict):
        found = {node["$ref"].rsplit("/", 1)[-1]} if "$ref" in node else set()
        for value in node.values():
            found |= _refs(value)
        return found
    if isinstance(node, list):
        return set().union(*(_refs(item) for item in node)) if node else set()
    return set()


# Bodies that are deliberately not a model; the handler checks them instead
# (routers/agent.py). Any other body without a $ref would pass the check below
# unseen.
_DICT_BODIES = {("post", "/agent/{server_id}/report")}


def test_every_request_schema_inherits_request_model():
    from app.main import app

    spec = app.openapi()
    components = spec["components"]["schemas"]
    todo = set()
    dict_bodies = set()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if "requestBody" not in operation:
                continue
            body = _refs(operation["requestBody"])
            if not body:
                dict_bodies.add((method, path))
            todo |= body
    assert dict_bodies == _DICT_BODIES
    names: set[str] = set()
    while todo:
        name = todo.pop()
        if name not in names:
            names.add(name)
            todo |= _refs(components[name]) - names
    # The instrument has to find something: one top-level body and one that is
    # only reachable nested inside another.
    assert {"CheckCreate", "TemplateCheckDef"} <= names

    models: dict[str, list[type[BaseModel]]] = {}
    stack = [BaseModel]
    while stack:
        for sub in stack.pop().__subclasses__():
            stack.append(sub)
            if sub.__module__.startswith("app.") and sub not in models.get(sub.__name__, []):
                models.setdefault(sub.__name__, []).append(sub)
    # One class per name, or the check below could look at the wrong one.
    assert sorted(n for n in names if len(models.get(n, [])) != 1) == []
    assert sorted(n for n in names if not issubclass(models[n][0], RequestModel)) == []
