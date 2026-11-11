# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Report version 4 (R-1223): the discovery, credentials and self blocks are additive.
Each is read on its own, a broken one costs only itself, a collector the agent
throttled leaves its checks as they were, and a report without them works as before."""

import json

import pytest

from app.core import victoria as victoria_mod
from app.models import MonitorCheck, MonitorDiscovery, MonitorFinding, MonitorState
from app.routers import agent as agent_router


def _discovery():
    return {
        "ts": 1762700000,
        "duration_ms": 900,
        "partial": False,
        "units": [{"name": "nginx.service", "state": "active", "sub": "running"}],
        "sockets": [
            {"proto": "tcp", "addr": "0.0.0.0", "port": 8443, "process": "java", "container": ""}
        ],
        "containers": [],
        "markers": {},
        "ports": [{"port": 8443, "proto": "tcp", "protocol": "https"}],
    }


def _add_check(factory, check_id, check_type, config=None):
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                server_id="srv-1",
                name=check_id,
                check_type=check_type,
                config=json.dumps(config or {}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()


def _set_state(factory, check_id, status, message):
    with factory() as db:
        db.add(MonitorState(check_id=check_id, status=status, message=message))
        db.commit()


def _state(factory, check_id):
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id=check_id).one_or_none()
        return None if state is None else (state.status, state.message)


def _discovery_row(factory):
    with factory() as db:
        row = db.get(MonitorDiscovery, "srv-1")
        if row is None:
            return None
        return {
            "scanned_at": row.scanned_at,
            "inventory": json.loads(row.inventory),
            "credentials": json.loads(row.credentials),
        }


def _post(client, report):
    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def written(monkeypatch):
    lines = []
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda batch: lines.extend(batch))
    return lines


def test_discovery_block_is_stored_and_makes_findings(client_db):
    client, factory = client_db

    body = _post(client, {"report_version": 4, "discovery": _discovery()})

    assert set(body) == {"status", "metricsWritten", "checksUpdated"}
    row = _discovery_row(factory)
    assert row["scanned_at"] is not None
    assert row["inventory"]["sockets"][0]["port"] == 8443
    with factory() as db:
        findings = [(f.module_id, f.instance_key, f.kind) for f in db.query(MonitorFinding)]
    assert findings == [("port", "tcp-8443", "new")]


def test_credentials_block_stores_only_valid_references(client_db):
    client, factory = client_db

    _post(
        client,
        {
            "credentials": {
                "paperless/paperless/api": True,
                "redis/cache/default": True,
                "x/../y": True,
                ".hidden/x": True,
                "a/b": False,
                "c/d": "the-secret",
                "e/f": 1,
                "g/h\n": True,
                "i" * 256: True,
            }
        },
    )
    stored = {"paperless/paperless/api": True, "redis/cache/default": True}
    assert _discovery_row(factory)["credentials"] == stored

    _post(client, {"resources": {"cpu_percent": 1.0}})
    assert _discovery_row(factory)["credentials"] == stored

    _post(client, {"credentials": {}})
    assert _discovery_row(factory)["credentials"] == {}


def test_credentials_block_is_bounded(client_db):
    client, factory = client_db
    from app.discovery import MAX_CREDENTIALS

    refs = {f"m/i/{n:04d}": True for n in range(MAX_CREDENTIALS + 10)}
    _post(client, {"credentials": refs})

    assert len(_discovery_row(factory)["credentials"]) == MAX_CREDENTIALS


@pytest.mark.parametrize(
    "blocks",
    [
        pytest.param({"discovery": "x", "credentials": [], "self": 5}, id="wrong-types"),
        pytest.param({"discovery": None, "credentials": None, "self": None}, id="null"),
        pytest.param({"self": {"collectors": []}}, id="collectors-list"),
        pytest.param({"self": {"collectors": {"docker": "x"}}}, id="collector-text"),
    ],
)
def test_broken_blocks_do_not_cost_the_report(client_db, blocks):
    client, factory = client_db
    _add_check(factory, "chk-res", "agent_resources", {"cpu_warn": 80, "cpu_crit": 95})

    body = _post(client, {"resources": {"cpu_percent": 10.0}, **blocks})

    assert body["checksUpdated"] == 1
    assert _state(factory, "chk-res")[0] == "ok"
    assert _discovery_row(factory) is None


def test_a_store_that_raises_costs_only_its_block(client_db, monkeypatch, caplog):
    client, factory = client_db
    _add_check(factory, "chk-res", "agent_resources", {"cpu_warn": 80, "cpu_crit": 95})

    def broken(db, server_id, block):
        # Half the work done when it fails: the next block must not commit it.
        db.add(MonitorDiscovery(server_id=server_id, inventory='{"half": true}'))
        db.flush()
        raise RuntimeError("boom")

    monkeypatch.setattr(agent_router, "apply_discovery", broken)

    body = _post(
        client,
        {
            "resources": {"cpu_percent": 10.0},
            "discovery": _discovery(),
            "credentials": {"paperless/paperless/api": True},
        },
    )

    assert body["checksUpdated"] == 1
    row = _discovery_row(factory)
    assert row["credentials"] == {"paperless/paperless/api": True}
    assert (row["scanned_at"], row["inventory"]) == (None, {})
    assert "Agent report block discovery of srv-1 dropped: RuntimeError" in caplog.text


def test_collector_figures_become_metrics(client_db, written):
    client, _ = client_db

    _post(
        client,
        {
            "self": {
                "collectors": {
                    "docker": {
                        "duration_ms": 210,
                        "cpu_ms": 40,
                        "timeouts": 0,
                        "factor": 1.5,
                        "throttled": False,
                    },
                    "zfs": {"duration_ms": -1, "cpu_ms": "40", "throttled": True},
                    "Bad Name": {"duration_ms": 1},
                    "x" * 33: {"duration_ms": 1},
                }
            }
        },
    )

    collector_lines = sorted(
        line.rsplit(" ", 1)[0] for line in written if line.startswith("monitor_agent_collector_")
    )
    assert collector_lines == [
        "monitor_agent_collector_cpu_ms,server_id=srv-1,collector=docker value=40i",
        "monitor_agent_collector_duration_ms,server_id=srv-1,collector=docker value=210i",
        "monitor_agent_collector_factor,server_id=srv-1,collector=docker value=1.5",
        "monitor_agent_collector_throttled,server_id=srv-1,collector=docker value=0i",
        "monitor_agent_collector_throttled,server_id=srv-1,collector=zfs value=1i",
        "monitor_agent_collector_timeouts,server_id=srv-1,collector=docker value=0i",
    ]


def test_throttled_collector_leaves_its_checks_as_they_were(client_db):
    client, factory = client_db
    _add_check(factory, "chk-docker", "docker_health")
    _set_state(factory, "chk-docker", "ok", "All 3 containers healthy")
    _add_check(factory, "chk-res", "agent_resources", {"cpu_warn": 80, "cpu_crit": 95})
    throttled = {"self": {"collectors": {"docker": {"throttled": True}}}}

    body = _post(client, {"resources": {"cpu_percent": 10.0}, **throttled})

    assert body["checksUpdated"] == 1
    assert _state(factory, "chk-docker") == ("ok", "All 3 containers healthy")
    assert _state(factory, "chk-res")[0] == "ok"

    # The same report from a collector that ran but sent nothing is rated.
    running = {"self": {"collectors": {"docker": {"throttled": False}}}}
    body = _post(client, {"resources": {"cpu_percent": 10.0}, **running})

    assert body["checksUpdated"] == 2
    assert _state(factory, "chk-docker") == ("unknown", "No Docker data in report")


@pytest.mark.parametrize("flag", ["true", 1, None])
def test_only_a_real_true_throttles(client_db, flag):
    client, factory = client_db
    _add_check(factory, "chk-docker", "docker_health")

    body = _post(client, {"self": {"collectors": {"docker": {"throttled": flag}}}})

    assert body["checksUpdated"] == 1


def test_a_throttled_collector_spares_only_its_own_checks(client_db):
    client, factory = client_db
    _add_check(factory, "chk-docker", "docker_health")
    _add_check(factory, "chk-zfs", "zfs_health")

    body = _post(client, {"self": {"collectors": {"zfs": {"throttled": True}}}})

    assert body["checksUpdated"] == 1
    assert _state(factory, "chk-zfs") is None
    assert _state(factory, "chk-docker")[0] == "unknown"


def test_report_v3_works_as_before(client_db, written):
    client, factory = client_db
    _add_check(factory, "chk-res", "agent_resources", {"cpu_warn": 80, "cpu_crit": 95})

    body = _post(client, {"report_version": 3, "resources": {"cpu_percent": 10.0}})

    assert body == {"status": "ok", "metricsWritten": 1, "checksUpdated": 1}
    assert _discovery_row(factory) is None
    assert not [line for line in written if line.startswith("monitor_agent_collector_")]
