# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The agent's load gate (R-1268): a collector it held back leaves its checks as they were,
with a note and without the throttle's time limit, as long as self.load_shed says the gate
is active; agent_resources warns after 30 minutes of it, and the gate's state is a metric."""

import json
from datetime import timedelta

import pytest

from app.core import victoria as victoria_mod
from app.core.time import utcnow_naive
from app.models import MonitorState

from .test_agent_report_v4 import _add_check, _post, _set_state, _state

RATED_LONG_AGO = timedelta(hours=2)


@pytest.fixture()
def client_db(client_db):
    # In pysqlite's legacy mode a SELECT runs outside any transaction, so the router's
    # SAVEPOINT opens one and its RELEASE commits it: a note written without the closing
    # commit would still land. PEP 249 mode keeps an outer transaction open, as Postgres does.
    _, factory = client_db
    with factory.kw["bind"].connect() as conn:
        conn.connection.driver_connection.autocommit = False
    return client_db


@pytest.fixture()
def written(monkeypatch):
    lines = []
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda batch: lines.extend(batch))
    return lines


def _since(ago):
    return (utcnow_naive() - ago).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gate(ago=timedelta(minutes=10), **block):
    return {"active": True, "over": ["load"], "since": _since(ago), **block}


def _shed(*collectors, gate=None, reason="load"):
    entry = {"throttled": True, "reason": reason}
    own = {"collectors": {name: dict(entry) for name in collectors}}
    if gate is not None:
        own["load_shed"] = gate
    return {"resources": {"cpu_percent": 10.0}, "self": own}


def _last_check(factory, check_id):
    with factory() as db:
        return db.query(MonitorState).filter_by(check_id=check_id).one().last_check


def _details(factory, check_id):
    with factory() as db:
        return json.loads(db.query(MonitorState).filter_by(check_id=check_id).one().details)


def test_a_shed_collector_spares_its_checks_beyond_the_throttle_limit(client_db):
    client, factory = client_db
    _add_check(factory, "chk-docker", "docker_health")
    _set_state(factory, "chk-docker", "ok", "All 3 containers healthy", RATED_LONG_AGO)
    rated = _last_check(factory, "chk-docker")

    body = _post(client, _shed("docker", gate=_gate()))

    assert body["checksUpdated"] == 0
    assert _state(factory, "chk-docker") == (
        "ok",
        "All 3 containers healthy (skipped: load shedding)",
    )
    assert _last_check(factory, "chk-docker") == rated


def test_the_note_is_replaced_and_goes_with_the_next_rating(client_db):
    client, factory = client_db
    _add_check(factory, "chk-docker", "docker_health")
    _set_state(factory, "chk-docker", "ok", "All 3 containers healthy (skipped: minimum spacing)")

    _post(client, _shed("docker", gate=_gate()))
    _post(client, _shed("docker", gate=_gate()))

    assert _state(factory, "chk-docker")[1] == "All 3 containers healthy (skipped: load shedding)"

    running = {"self": {"collectors": {"docker": {"throttled": False}}}}
    body = _post(client, running)

    assert body["checksUpdated"] == 1
    assert _state(factory, "chk-docker") == ("unknown", "No Docker data in report")


def test_a_shed_collector_spares_no_check_without_a_rating(client_db):
    client, factory = client_db
    _add_check(factory, "chk-docker", "docker_health")

    body = _post(client, _shed("docker", gate=_gate()))

    assert body["checksUpdated"] == 1
    assert _state(factory, "chk-docker") == ("unknown", "No Docker data in report")


def test_shed_probes_spare_the_probe_checks(client_db):
    client, factory = client_db
    _add_check(factory, "chk-probe", "probe", {"module": "http"})
    _set_state(factory, "chk-probe", "critical", "HTTP 503", RATED_LONG_AGO)

    body = _post(client, _shed("probes", gate=_gate()))

    assert body["checksUpdated"] == 0
    assert _state(factory, "chk-probe") == ("critical", "HTTP 503 (skipped: load shedding)")


@pytest.mark.parametrize(
    ("gate", "reason"),
    [
        pytest.param(None, "load", id="no-block"),
        pytest.param(_gate(active=False), "load", id="inactive"),
        pytest.param(_gate(active="true"), "load", id="active-text"),
        pytest.param(_gate(since=None), "load", id="no-since"),
        pytest.param(_gate(since="12.11.2026 10:00"), "load", id="since-garbage"),
        pytest.param(_gate(since=1762900000), "load", id="since-number"),
        pytest.param(_gate(), "busy", id="other-reason"),
        pytest.param(_gate(), None, id="no-reason"),
    ],
)
def test_without_an_active_gate_the_throttle_limit_holds(client_db, gate, reason):
    client, factory = client_db
    _add_check(factory, "chk-docker", "docker_health")
    _set_state(factory, "chk-docker", "ok", "All 3 containers healthy", timedelta(minutes=46))

    body = _post(client, _shed("docker", gate=gate, reason=reason))

    assert body["checksUpdated"] == 1
    assert _state(factory, "chk-docker") == ("unknown", "No Docker data in report")


def test_a_shed_collector_spares_only_its_own_checks(client_db):
    client, factory = client_db
    _add_check(factory, "chk-docker", "docker_health")
    _set_state(factory, "chk-docker", "ok", "All 3 containers healthy", RATED_LONG_AGO)
    _add_check(factory, "chk-zfs", "zfs_health")
    _set_state(factory, "chk-zfs", "ok", "Pool healthy", RATED_LONG_AGO)

    body = _post(client, _shed("zfs", gate=_gate()))

    assert body["checksUpdated"] == 1
    assert _state(factory, "chk-zfs") == ("ok", "Pool healthy (skipped: load shedding)")
    assert _state(factory, "chk-docker") == ("unknown", "No Docker data in report")


@pytest.mark.parametrize(
    ("block", "line"),
    [
        pytest.param(_gate(), "monitor_agent_load_shed,server_id=srv-1 value=1i", id="active"),
        pytest.param(
            {"active": False, "over": [], "values": {}},
            "monitor_agent_load_shed,server_id=srv-1 value=0i",
            id="inactive",
        ),
        pytest.param({"active": "yes"}, None, id="active-text"),
        pytest.param({}, None, id="empty"),
        pytest.param(["active"], None, id="list"),
    ],
)
def test_the_gate_state_is_a_metric(client_db, written, block, line):
    client, _ = client_db

    _post(client, {"self": {"load_shed": block}})

    lines = [row.rsplit(" ", 1)[0] for row in written if row.startswith("monitor_agent_load_shed")]
    assert lines == ([line] if line else [])


def test_a_report_without_the_block_writes_no_gate_metric(client_db, written):
    client, _ = client_db

    _post(client, {"resources": {"cpu_percent": 10.0}, "self": {"collectors": {}}})

    assert not [row for row in written if row.startswith("monitor_agent_load_shed")]


@pytest.mark.parametrize(
    ("ago", "status"),
    [
        pytest.param(timedelta(minutes=29, seconds=30), "ok", id="29-min"),
        pytest.param(timedelta(minutes=30, seconds=5), "warning", id="30-min"),
        pytest.param(timedelta(hours=26), "warning", id="26-h"),
        pytest.param(-timedelta(hours=1), "ok", id="since-ahead"),
    ],
)
def test_agent_resources_warns_after_30_minutes_of_shedding(client_db, ago, status):
    client, factory = client_db
    _add_check(factory, "chk-res", "agent_resources", {"cpu_warn": 80, "cpu_crit": 95})

    _post(client, _shed("docker", gate=_gate(ago)))

    rated, message = _state(factory, "chk-res")
    problems = _details(factory, "chk-res").get("problems", {})
    assert rated == status
    if status == "warning":
        minutes = int(ago.total_seconds() // 60)
        assert message == f"Load shedding for {minutes} min (>=30 min)"
        assert problems == {"load_shed": "warning"}
    else:
        assert message == "CPU 10.0%"
        assert problems == {}


@pytest.mark.parametrize(
    "gate",
    [
        pytest.param(_gate(timedelta(hours=1), active=False), id="inactive"),
        pytest.param(_gate(timedelta(hours=1), since="yesterday"), id="since-garbage"),
        pytest.param(None, id="no-block"),
    ],
)
def test_agent_resources_does_not_warn_without_an_active_gate(client_db, gate):
    client, factory = client_db
    _add_check(factory, "chk-res", "agent_resources", {"cpu_warn": 80, "cpu_crit": 95})

    _post(client, _shed("docker", gate=gate))

    assert _state(factory, "chk-res") == ("ok", "CPU 10.0%")
    assert "load_shed" not in _details(factory, "chk-res").get("problems", {})
