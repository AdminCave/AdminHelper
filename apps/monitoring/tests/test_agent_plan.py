# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The agent's plan (R-1223): only the server's own agent key reads it, it lists the
server's enabled probe checks as their configs hold today, the catalog's markers and
whether the agent scans in this run."""

import json
import logging
from datetime import timedelta

import pytest

from app import module_plan
from app.catalog.loader import load_catalog
from app.core.auth import require_agent
from app.core.time import utcnow_naive
from app.models import MonitorAgentKey, MonitorCheck, MonitorDiscovery

_PROBE = {
    "sensor": "http",
    "target": {"kind": "container", "name": "paperless-web-1", "port_hint": 8000, "scheme": "http"},
    "params": {"path": "/api/status/"},
    "interval_s": 900,
    "timeout_s": 5,
    "fields": ["status_code"],
    "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
    "credential": {"ref": "paperless/paperless/api", "use": "bearer"},
}


def _add_check(
    factory,
    check_id,
    config,
    server_id="srv-1",
    check_type="probe",
    enabled=True,
    module_id="paperless",
):
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                server_id=server_id,
                name=check_id,
                check_type=check_type,
                config=config if isinstance(config, str) else json.dumps(config),
                enabled=enabled,
                module_id=module_id,
            )
        )
        db.commit()


def _plan(client, server_id="srv-1"):
    r = client.get(f"/agent/{server_id}/plan")
    assert r.status_code == 200, r.text
    return r.json()


def test_plan_lists_the_servers_enabled_probe_checks(client_db):
    client, factory = client_db
    _add_check(factory, "chk-a", _PROBE)
    _add_check(factory, "chk-off", _PROBE, enabled=False)
    _add_check(factory, "chk-other", _PROBE, server_id="srv-2")
    _add_check(factory, "chk-res", {"cpu_warn": 80}, check_type="agent_resources")

    assert _plan(client)["probes"] == [
        {
            "id": "chk-a",
            "sensor": "http",
            "interval_s": 900,
            "timeout_s": 5,
            "target": {
                "kind": "container",
                "name": "paperless-web-1",
                "port_hint": 8000,
                "scheme": "http",
            },
            "params": {"path": "/api/status/"},
            "fields": ["status_code"],
            "credential": {"ref": "paperless/paperless/api", "use": "bearer"},
        }
    ]


def test_plan_carries_no_rules_and_defaults_for_what_the_config_leaves_out(client_db):
    client, factory = client_db
    _add_check(factory, "chk-min", {"sensor": "log", "fields": ["count"]})

    assert _plan(client)["probes"] == [
        {
            "id": "chk-min",
            "sensor": "log",
            "interval_s": 300,
            "timeout_s": 10,
            "target": None,
            "params": {},
            "fields": ["count"],
            "credential": None,
        }
    ]


def test_plan_of_a_new_server_is_empty_and_scans_at_once(client_db, monkeypatch):
    client, _ = client_db
    # Without markers: the shipped modules bring their own, and which they are is
    # test_markers_come_from_the_whole_catalog_sorted's business, not this one's.
    catalog = load_catalog([])
    monkeypatch.setattr(module_plan, "get_catalog", lambda: catalog)

    assert _plan(client) == {
        "plan_version": 1,
        "catalog_version": catalog.version,
        "scan": True,
        "discovery": {"markers": []},
        "probes": [],
    }


def test_scan_flag_follows_the_schedule_and_scan_now(client_db):
    client, factory = client_db
    now = utcnow_naive()
    with factory() as db:
        db.add(
            MonitorDiscovery(
                server_id="srv-1",
                scanned_at=now - timedelta(hours=1),
                next_scan_at=now + timedelta(hours=23),
            )
        )
        db.commit()
    assert _plan(client)["scan"] is False

    with factory() as db:
        db.get(MonitorDiscovery, "srv-1").scan_requested_at = now
        db.commit()
    assert _plan(client)["scan"] is True

    with factory() as db:
        row = db.get(MonitorDiscovery, "srv-1")
        row.scan_requested_at = None
        row.next_scan_at = now - timedelta(minutes=1)
        db.commit()
    assert _plan(client)["scan"] is True


def test_markers_come_from_the_whole_catalog_sorted(client_db, monkeypatch):
    client, _ = client_db

    def _module(module_id, markers):
        return (
            module_id,
            {
                "id": module_id,
                "name": module_id,
                "version": 1,
                "instance": "unit",
                "detect": {"markers": markers},
                "checks": [
                    {
                        "key": "up",
                        "name": "Up",
                        "sensor": "unit",
                        "target": {"kind": "unit"},
                        "interval": 300,
                        "fields": ["active_state"],
                    }
                ],
            },
        )

    catalog = load_catalog(
        [
            _module("zeta", [{"id": "zeta.conf", "paths": ["/etc/zeta.conf"]}]),
            _module(
                "alpha",
                [
                    {"id": "alpha.pkg", "packages": ["alpha"]},
                    {"id": "alpha.conf", "paths": ["/etc/alpha"], "packages": ["alpha-server"]},
                ],
            ),
        ]
    )
    assert catalog.errors == ()
    monkeypatch.setattr(module_plan, "get_catalog", lambda: catalog)

    plan = _plan(client)

    assert plan["catalog_version"] == catalog.version
    assert plan["discovery"]["markers"] == [
        {"id": "alpha.conf", "paths": ["/etc/alpha"], "packages": ["alpha-server"]},
        {"id": "alpha.pkg", "paths": [], "packages": ["alpha"]},
        {"id": "zeta.conf", "paths": ["/etc/zeta.conf"], "packages": []},
    ]


@pytest.mark.parametrize(
    "config",
    [
        pytest.param("{", id="broken-json"),
        pytest.param("[]", id="no-object"),
        pytest.param({**_PROBE, "sensor": "telnet"}, id="unknown-sensor"),
        pytest.param({**_PROBE, "credential": {"ref": "../etc/shadow", "use": "bearer"}}, id="ref"),
        pytest.param({**_PROBE, "target": {**_PROBE["target"], "name": "a\nb"}}, id="name"),
        pytest.param({**_PROBE, "timeout_s": 300}, id="timeout"),
        pytest.param({**_PROBE, "shell": "id"}, id="unknown-key"),
    ],
)
def test_a_stored_config_that_no_longer_holds_never_reaches_the_agent(client_db, config, caplog):
    client, factory = client_db
    _add_check(factory, "chk-bad", config)
    _add_check(factory, "chk-good", _PROBE)

    with caplog.at_level(logging.WARNING, logger="app.module_plan"):
        probes = _plan(client)["probes"]

    assert [p["id"] for p in probes] == ["chk-good"]
    assert "Probe check chk-bad left out of the plan" in caplog.text


def test_plan_only_for_the_servers_own_agent_key(client_db):
    from app.main import app

    client, factory = client_db
    _add_check(factory, "chk-a", _PROBE)

    app.dependency_overrides[require_agent] = lambda: "srv-2"
    r = client.get("/agent/srv-1/plan")
    assert (r.status_code, r.json()["detail"]) == (403, "API key does not belong to this server")

    app.dependency_overrides[require_agent] = lambda: "__internal__"
    assert [p["id"] for p in _plan(client)["probes"]] == ["chk-a"]


def test_plan_checks_the_agent_key_like_the_report(client_db):
    from app.main import app

    client, factory = client_db
    del app.dependency_overrides[require_agent]
    with factory() as db:
        db.add(
            MonitorAgentKey(id="k1", server_id="srv-1", hashed_key=MonitorAgentKey.hash_key("raw"))
        )
        db.commit()

    assert client.get("/agent/srv-1/plan").status_code == 401
    assert client.get("/agent/srv-1/plan", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/agent/srv-2/plan", headers={"X-API-Key": "raw"}).status_code == 403
    assert client.get("/agent/srv-1/plan", headers={"X-API-Key": "raw"}).status_code == 200


def test_plan_leaves_out_a_probe_check_no_module_brought(client_db):
    # R-1252: a probe check comes only from a module of the catalog; one without (an older
    # row, a template's) never reaches the agent.
    client, factory = client_db
    _add_check(factory, "chk-module", _PROBE)
    _add_check(factory, "chk-loose", _PROBE, module_id=None)

    assert [p["id"] for p in _plan(client)["probes"]] == ["chk-module"]
