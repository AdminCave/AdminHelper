# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The admin API of the service list (R-1226): the inventory, the switch for the error
lines per server and the redacted lines of failed services; the plan carries the switch
to the agent."""

import json

import pytest

from app.core.time import utcnow_naive
from app.models import MonitorAgentKey, MonitorServiceInventory, MonitorServiceLog

_URL = "/status/server/srv-1/services"


def _report():
    return {
        "systemd": {
            "failed": ["nginx.service"],
            "enabled_inactive": [],
            "failed_logs": {
                "nginx.service": {
                    "since": "2026-11-12T10:00:00Z",
                    "lines": ["starting", "token=abc123 rejected"],
                }
            },
            "all_services": [
                {"unit": "nginx.service", "active_state": "failed", "result": "exit-code"},
                {"unit": "ssh.service", "active_state": "active", "memory_bytes": "4096"},
            ],
        }
    }


def _push(client, report):
    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200, r.text


def _add_key(factory, server_id="srv-1"):
    with factory() as db:
        db.add(
            MonitorAgentKey(
                id=f"k-{server_id}",
                server_id=server_id,
                hashed_key=MonitorAgentKey.hash_key(server_id),
            )
        )
        db.commit()


def _options(client, body, server_id="srv-1"):
    return client.put(f"/status/server/{server_id}/services/options", json=body)


def test_an_unknown_server_is_404_and_a_put_leaves_no_row(client_db):
    client, factory = client_db

    assert client.get(_URL).status_code == 404
    r = _options(client, {"log_lines": False})

    assert (r.status_code, r.json()["detail"]) == (404, "Server not found")
    with factory() as db:
        assert db.get(MonitorServiceInventory, "srv-1") is None


def test_a_server_with_a_key_and_no_report_has_an_empty_list(client_db):
    client, factory = client_db
    _add_key(factory)

    r = client.get(_URL)

    assert r.status_code == 200, r.text
    assert r.json() == {
        "serverId": "srv-1",
        "reportedAt": None,
        "logLines": True,
        "services": [],
        "logs": {},
    }


def test_a_server_whose_agent_reported_is_known_without_a_key(client_db):
    # An agent enrolled with a certificate reports through the server and holds no key here.
    client, _ = client_db
    _push(client, {"resources": {"cpu_percent": 1.0}})

    r = client.get(_URL)

    assert (r.status_code, r.json()["services"], r.json()["reportedAt"]) == (200, [], None)


def test_the_list_carries_the_inventory_and_the_redacted_lines(client_db):
    client, _ = client_db
    _push(client, _report())

    body = client.get(_URL).json()

    assert body["reportedAt"].endswith("Z")
    assert body["logLines"] is True
    assert body["services"] == _report()["systemd"]["all_services"]
    log = body["logs"]["nginx.service"]
    assert log["since"] == "2026-11-12T10:00:00Z"
    assert log["collectedAt"].endswith("Z")
    assert log["lines"] == ["starting", "token=[REDACTED] rejected"]


def test_the_switch_off_deletes_the_lines_and_the_agent_sends_none(client_db):
    client, factory = client_db
    _push(client, _report())

    r = _options(client, {"log_lines": False})

    assert r.status_code == 200, r.text
    assert (r.json()["logLines"], r.json()["logs"]) == (False, {})
    assert len(r.json()["services"]) == 2
    with factory() as db:
        assert db.query(MonitorServiceLog).count() == 0
    assert client.get("/agent/srv-1/plan").json()["service_logs"] is False
    # Lines an agent sends anyway are not stored.
    _push(client, _report())
    with factory() as db:
        assert db.query(MonitorServiceLog).count() == 0

    r = _options(client, {"log_lines": True})

    assert r.json()["logLines"] is True
    assert client.get("/agent/srv-1/plan").json()["service_logs"] is True
    _push(client, _report())
    assert client.get(_URL).json()["logs"]["nginx.service"]["lines"][0] == "starting"


def test_the_switch_can_be_set_before_the_first_report(client_db):
    client, factory = client_db
    _add_key(factory)

    r = _options(client, {"log_lines": False})

    assert r.status_code == 200, r.text
    assert r.json() == {
        "serverId": "srv-1",
        "reportedAt": None,
        "logLines": False,
        "services": [],
        "logs": {},
    }
    _push(client, _report())
    body = client.get(_URL).json()
    assert (body["logLines"], body["logs"], len(body["services"])) == (False, {}, 2)


def test_lines_stored_while_the_switch_is_off_are_not_shown(client_db):
    # A report already running when the switch went off stores its lines once more.
    client, factory = client_db
    with factory() as db:
        db.add(MonitorServiceInventory(server_id="srv-1", log_lines=False))
        db.add(
            MonitorServiceLog(
                server_id="srv-1",
                unit="nginx.service",
                collected_at=utcnow_naive(),
                lines=json.dumps(["late"]),
            )
        )
        db.commit()

    assert client.get(_URL).json()["logs"] == {}


def test_the_switch_is_per_server(client_db):
    client, factory = client_db
    _add_key(factory, "srv-2")
    _push(client, _report())

    _options(client, {"log_lines": False}, server_id="srv-2")

    assert client.get(_URL).json()["logs"]["nginx.service"]["lines"]
    with factory() as db:
        assert db.get(MonitorServiceInventory, "srv-1").log_lines is True
        assert db.get(MonitorServiceInventory, "srv-2").log_lines is False


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"log_lines": "false"},
        {"log_lines": 0},
        {"log_lines": None},
        {"log_lines": False, "unit": "nginx.service"},
        {"logLines": False},
    ],
)
def test_the_options_take_exactly_one_boolean(client_db, body):
    client, factory = client_db
    _add_key(factory)

    assert _options(client, body).status_code == 422
    with factory() as db:
        assert db.get(MonitorServiceInventory, "srv-1") is None


def _inventory_locks(factory):
    """The statements on the inventory table a session of `factory` runs from now on, as
    Postgres gets them: sqlite drops FOR UPDATE, the stack's database takes it."""
    from sqlalchemy import event
    from sqlalchemy.dialects import postgresql

    seen = []

    @event.listens_for(factory, "do_orm_execute")
    def _record(state):
        sql = str(state.statement.compile(dialect=postgresql.dialect()))
        if "monitor_service_inventory" in sql:
            seen.append(sql)

    return seen


@pytest.mark.parametrize("server_has_row", [False, True])
def test_the_switch_locks_the_inventory_a_report_writes(client_db, server_has_row):
    # R-1415: switch and report take the same row lock, so lines of a report in flight
    # are gone once the switch is off.
    client, factory = client_db
    if server_has_row:
        _push(client, _report())
    else:
        _add_key(factory)
    seen = _inventory_locks(factory)

    assert _options(client, {"log_lines": False}).status_code == 200

    # _known_server and the reload after the commit read without a lock; the read the
    # switch is written on holds it.
    assert any("FOR UPDATE" in sql for sql in seen), seen


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", _URL, None),
        ("PUT", f"{_URL}/options", {"log_lines": False}),
    ],
    ids=["list", "options"],
)
@pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "wrong"}], ids=["none", "wrong"])
def test_the_service_routes_need_the_internal_key(
    client_db, monkeypatch, method, path, body, headers
):
    # R-1415: both routes sit behind require_internal; without it the list showed the
    # redacted lines and the switch was open to anyone reaching the service.
    from app.core import auth
    from app.core.auth import require_internal
    from app.main import app

    client, factory = client_db
    _push(client, _report())
    monkeypatch.setattr(auth, "INTERNAL_API_KEY", "right-key")
    del app.dependency_overrides[require_internal]

    r = client.request(method, path, json=body, headers=headers)

    assert r.status_code == 401
    with factory() as db:
        assert db.get(MonitorServiceInventory, "srv-1").log_lines is not False
        assert db.query(MonitorServiceLog).count() == 1
    ok = client.request(method, path, json=body, headers={"X-Internal-Key": "right-key"})
    assert ok.status_code == 200, ok.text
