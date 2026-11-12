# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Taking over findings (R-1223): adopting binds the module's catalog checks to the
instance or switches them on, adopting "gone" switches them off and nothing is ever
deleted; at start-up a changed catalog adds its new checks silent to adopted instances
and reopens the finding, a dropped check stays; an adopted instance back from "gone"
after a catalog update waits for the admin."""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import module_sync
from app.catalog.loader import load_catalog
from app.catalog.modules.port import MODULE as PORT_MODULE
from app.check_configs import ProbeConfig
from app.discovery import apply_discovery
from app.models import Base, MonitorCheck, MonitorDiscovery, MonitorFinding, MonitorState
from app.module_sync import AdoptError, adopt, adopt_all, dismiss, probe_config, sync_catalog

# Far from the real clock: nothing here may depend on today.
NOW = datetime(2020, 1, 1, 12, 0)
PAPERLESS_IMAGE = "ghcr.io/paperless-ngx/paperless-ngx"

WEB = {
    "key": "web",
    "name": "Web",
    "sensor": "http",
    "target": {"kind": "container", "port_hint": 8000, "scheme": "http"},
    "params": {"path": "/api/"},
    "interval": 300,
    "fields": ["status_code"],
    "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
    "credential": {"slot": "api", "use": "bearer"},
}
BROKER = {
    "key": "broker",
    "name": "Broker",
    "sensor": "container",
    "target": {"kind": "container", "service": "broker"},
    "interval": 300,
    "fields": ["state"],
}
# A unit check of a compose project: no unit belongs to the instance, so it never binds.
SCHED = {
    "key": "sched",
    "name": "Scheduler",
    "sensor": "unit",
    "target": {"kind": "unit"},
    "interval": 900,
    "fields": ["active_state"],
}
HEALTH = {
    "key": "health",
    "name": "Health",
    "sensor": "container",
    "target": {"kind": "container"},
    "interval": 900,
    "fields": ["health"],
}


def _paperless(*checks, description=""):
    return (
        "paperless",
        {
            "id": "paperless",
            "name": "Paperless",
            "version": 1,
            "description": description,
            "instance": "compose_project",
            "detect": {"container_images": [PAPERLESS_IMAGE], "units": ["paperless-scheduler"]},
            "checks": list(checks),
        },
    )


NGINX = (
    "nginx",
    {
        "id": "nginx",
        "name": "nginx",
        "version": 1,
        "instance": "unit",
        "detect": {"units": ["nginx"], "processes": ["nginx"]},
        "checks": [
            {
                "key": "up",
                "name": "Up",
                "sensor": "unit",
                "target": {"kind": "unit"},
                "interval": 300,
                "fields": ["active_state"],
            },
            {
                "key": "workers",
                "name": "Workers",
                "sensor": "process",
                "target": {"kind": "process"},
                "interval": 300,
                "fields": ["count"],
            },
        ],
    },
)

V1 = load_catalog([_paperless(WEB, BROKER, SCHED), NGINX, ("port", PORT_MODULE)])
WITH_HEALTH = load_catalog([_paperless(WEB, BROKER, SCHED, HEALTH), NGINX, ("port", PORT_MODULE)])
WITHOUT_BROKER = load_catalog([_paperless(WEB, SCHED), NGINX, ("port", PORT_MODULE)])
UNBINDABLE_ADDED = load_catalog(
    [_paperless(WEB, BROKER, SCHED, {**SCHED, "key": "sched2"}), NGINX, ("port", PORT_MODULE)]
)
REWORDED = load_catalog(
    [_paperless(WEB, BROKER, SCHED, description="Reworded."), NGINX, ("port", PORT_MODULE)]
)
NO_PAPERLESS = load_catalog([NGINX, ("port", PORT_MODULE)])


def test_test_catalogs_are_valid():
    catalogs = (V1, WITH_HEALTH, WITHOUT_BROKER, UNBINDABLE_ADDED, REWORDED, NO_PAPERLESS)
    assert [c.errors for c in catalogs] == [()] * len(catalogs)
    assert len({c.version for c in catalogs}) == len(catalogs)


def _container(name, image, project="", service=""):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": "",
        "ports": [],
        "mounts": [],
    }


# One container per service of the project; several of one service bind none (own test).
CONTAINERS = [
    _container("paperless-web-1", PAPERLESS_IMAGE + ":2.14", "paperless", "webserver"),
    _container("paperless-broker-1", "docker.io/library/redis:7", "paperless", "broker"),
    _container("other-broker-1", "docker.io/library/redis:7", "other", "broker"),
]
PROJECT_SUMMARY = {"services": {"broker": "redis", "webserver": PAPERLESS_IMAGE}}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def actions(monkeypatch):
    """The scheduler mutations adopting hands on after its commit."""
    seen = []
    monkeypatch.setattr(module_sync, "apply_scheduler_actions", seen.extend)
    return seen


def _inventory(db, containers=CONTAINERS, server_id="srv-1"):
    db.add(MonitorDiscovery(server_id=server_id, inventory=json.dumps({"containers": containers})))
    db.commit()


def _finding(
    db,
    module_id="paperless",
    key="paperless",
    *,
    kind="new",
    status="open",
    summary=PROJECT_SUMMARY,
    server_id="srv-1",
):
    finding = MonitorFinding(
        id=f"f-{server_id}-{module_id}-{key}",
        server_id=server_id,
        module_id=module_id,
        instance_key=key,
        kind=kind,
        status=status,
        summary=json.dumps(summary),
        catalog_version="before",
    )
    db.add(finding)
    db.commit()
    return finding


def _checks(db, finding):
    return {row.module_check_key: row for row in module_sync.instance_checks(db, finding)}


def _reopen(db, finding, kind):
    finding.kind, finding.status = kind, "open"
    db.commit()


# --- binding a catalog check to the instance ---------------------------------------


def _bind(module_id, key, check_key, summary, containers=CONTAINERS, catalog=V1):
    module = catalog.modules[module_id]
    check = next(c for c in module.checks if c.key == check_key)
    return probe_config(module, check, key, summary, containers)


def test_a_bound_check_carries_the_instance_and_holds():
    config, reason = _bind("paperless", "paperless", "web", PROJECT_SUMMARY)

    assert reason is None
    assert config == {
        "sensor": "http",
        "target": {
            "kind": "container",
            "name": "paperless-web-1",
            "port_hint": 8000,
            "scheme": "http",
        },
        "params": {"path": "/api/", "method": "GET"},
        "interval_s": 300,
        "timeout_s": 10,
        "fields": ["status_code"],
        "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        "credential": {"ref": "paperless/paperless/api", "use": "bearer"},
        "test_object": False,
    }
    ProbeConfig.model_validate(config)


@pytest.mark.parametrize(
    ("module_id", "key", "check_key", "summary", "name", "reason"),
    [
        pytest.param(
            "paperless", "paperless", "broker", PROJECT_SUMMARY, "paperless-broker-1", None,
            id="service-of-the-project",
        ),
        pytest.param(
            "paperless", "paperless", "sched", PROJECT_SUMMARY, None,
            "no unit for this instance", id="no-unit-in-a-project",
        ),
        pytest.param(
            "paperless", "paperless-solo", "web",
            {"container": "paperless-solo", "image": PAPERLESS_IMAGE}, "paperless-solo", None,
            id="container-without-project",
        ),
        pytest.param(
            "paperless", "paperless-solo", "broker",
            {"container": "paperless-solo", "image": PAPERLESS_IMAGE}, None,
            "no container for this instance", id="no-other-service-without-project",
        ),
        pytest.param(
            "paperless", "paperless", "web",
            {"matched_by": ["unit:paperless-scheduler.service"]}, None,
            "no container for this instance", id="stand-in-has-no-container",
        ),
        pytest.param(
            "nginx", "nginx.service", "up", {"unit": "nginx.service"}, "nginx.service", None,
            id="own-kind-is-the-key",
        ),
        pytest.param(
            "nginx", "nginx.service", "workers", {"unit": "nginx.service"}, None,
            "no process for this instance", id="other-kind-of-a-unit",
        ),
        pytest.param(
            "nginx", "nginx", "workers", {"matched_by": ["process:nginx"]}, "nginx", None,
            id="stand-in-one-process",
        ),
        pytest.param(
            "nginx", "nginx", "workers", {"matched_by": ["process:nginx", "process:nginx-dbg"]},
            None, "no process for this instance", id="stand-in-two-processes",
        ),
        pytest.param(
            "nginx", "nginx", "up", {"matched_by": ["process:nginx"]}, None,
            "no unit for this instance", id="stand-in-without-unit",
        ),
    ],
)  # fmt: skip
def test_target_names(module_id, key, check_key, summary, name, reason):
    config, why = _bind(module_id, key, check_key, summary)

    assert why == reason
    assert (None if config is None else config["target"]["name"]) == name


def test_several_containers_of_a_service_bind_none_and_are_named(db, actions):
    replicas = [
        *CONTAINERS,
        _container("paperless-web-0", PAPERLESS_IMAGE + ":2.14", "paperless", "webserver"),
    ]
    reason = "several containers for this instance: paperless-web-0, paperless-web-1"

    assert _bind("paperless", "paperless", "web", PROJECT_SUMMARY, containers=replicas) == (
        None,
        reason,
    )
    _inventory(db, containers=replicas)
    result = adopt(db, _finding(db).id, catalog=V1)

    assert {"key": "web", "reason": reason} in result.skipped
    assert "web" not in _checks(db, result.finding)


def test_no_inventory_no_container():
    assert _bind("paperless", "paperless", "web", PROJECT_SUMMARY, containers=[]) == (
        None,
        "no container for this instance",
    )


def _tcp(*ports, proto="tcp"):
    return [{"private": p, "public": None, "proto": proto} for p in ports]


@pytest.mark.parametrize(
    ("ports", "reason"),
    [
        pytest.param(_tcp(9000), "container paperless-web-1 has no port 8000", id="other-port"),
        pytest.param(_tcp(8000, proto="udp") + _tcp(9000),
                     "container paperless-web-1 has no port 8000", id="hint-only-as-udp"),
        pytest.param(_tcp(8000, 9000), None, id="hint-among-ports"),
        pytest.param([], None, id="no-ports-seen"),
        pytest.param(_tcp(8000, proto="udp"), None, id="no-tcp-port-seen"),
    ],
)  # fmt: skip
def test_a_container_without_the_hinted_port_binds_no_check(ports, reason):
    web = {**CONTAINERS[0], "ports": ports}

    config, why = _bind("paperless", "paperless", "web", PROJECT_SUMMARY, [web, *CONTAINERS[1:]])

    assert why == reason
    assert (config is None) == (reason is not None)


def test_a_port_takes_the_found_port():
    config, _ = _bind("port", "tcp-8443", "answers", {"port": 8443, "protocol": "https"})

    assert config["target"] == {"kind": "port", "name": "", "port_hint": 8443, "scheme": None}
    assert _bind("port", "tcp-8443", "answers", {}) == (None, "no port for this instance")


# --- adopting ----------------------------------------------------------------------


def test_adopting_new_creates_the_checks_alerting(db, actions):
    _inventory(db)
    finding = _finding(db)

    result = adopt(db, finding.id, catalog=V1, now=NOW)

    checks = _checks(db, finding)
    assert set(checks) == {"web", "broker"}
    assert result.enabled == [checks["web"].id, checks["broker"].id]
    assert result.skipped == [{"key": "sched", "reason": "no unit for this instance"}]
    for row in checks.values():
        assert (row.check_type, row.enabled, row.silent, row.interval) == (
            "probe",
            True,
            False,
            "5m",
        )
        assert (row.server_id, row.module_id, row.module_instance) == (
            "srv-1",
            "paperless",
            "paperless",
        )
        assert db.get(MonitorState, row.id).status == "pending"
    assert checks["web"].name == "Paperless (paperless): Web"
    assert json.loads(checks["broker"].config)["target"]["name"] == "paperless-broker-1"
    assert (finding.status, finding.decided_at, finding.catalog_version) == (
        "adopted",
        NOW,
        V1.version,
    )
    assert actions == [
        ("add", checks["web"].id, "5m", "probe"),
        ("add", checks["broker"].id, "5m", "probe"),
    ]


def test_adopting_twice_creates_nothing_twice(db, actions):
    _inventory(db)
    finding = _finding(db)
    adopt(db, finding.id, catalog=V1, now=NOW)
    first = {key: row.id for key, row in _checks(db, finding).items()}

    adopt(db, finding.id, catalog=V1, now=NOW)

    assert {key: row.id for key, row in _checks(db, finding).items()} == first
    assert db.query(MonitorCheck).count() == 2


def test_adopting_changed_keeps_a_check_the_admin_switched_off(db, actions):
    _inventory(db)
    finding = _finding(db)
    adopt(db, finding.id, catalog=V1, now=NOW)
    checks = _checks(db, finding)
    checks["broker"].enabled = False
    checks["web"].silent = True
    _reopen(db, finding, "changed")
    actions.clear()

    result = adopt(db, finding.id, catalog=V1, now=NOW)

    assert (checks["web"].enabled, checks["web"].silent) == (True, False)
    assert (checks["broker"].enabled, checks["broker"].silent) == (False, False)
    assert result.enabled == [checks["web"].id]
    assert actions == [("add", checks["web"].id, "5m", "probe")]


def test_adopting_gone_switches_off_and_deletes_nothing(db, actions):
    _inventory(db)
    finding = _finding(db)
    adopt(db, finding.id, catalog=V1, now=NOW)
    checks = _checks(db, finding)
    checks["broker"].enabled = False
    _reopen(db, finding, "gone")
    actions.clear()

    result = adopt(db, finding.id, catalog=V1, now=NOW)

    assert set(_checks(db, finding)) == {"web", "broker"}
    assert not any(row.enabled for row in checks.values())
    assert result.disabled == [checks["web"].id]
    assert actions == [("remove", checks["web"].id, None, None)]
    assert finding.status == "adopted"


def test_adopting_new_again_switches_the_whole_instance_on(db, actions):
    _inventory(db)
    finding = _finding(db)
    adopt(db, finding.id, catalog=V1, now=NOW)
    _reopen(db, finding, "gone")
    adopt(db, finding.id, catalog=V1, now=NOW)
    _reopen(db, finding, "new")

    result = adopt(db, finding.id, catalog=V1, now=NOW)

    assert all(row.enabled for row in _checks(db, finding).values())
    assert len(result.enabled) == 2


def test_adopting_a_module_the_catalog_lost_fails_and_changes_nothing(db, actions):
    finding = _finding(db)

    with pytest.raises(AdoptError, match="no longer in the catalog"):
        adopt(db, finding.id, catalog=NO_PAPERLESS, now=NOW)

    db.rollback()
    assert (finding.status, finding.catalog_version) == ("open", "before")
    assert db.query(MonitorCheck).count() == 0


def test_unknown_findings(db, actions):
    assert adopt(db, "nope", catalog=V1, now=NOW) is None
    assert dismiss(db, "nope", now=NOW) is None


def test_adopt_all_takes_the_servers_open_findings(db, actions):
    _inventory(db)
    project = _finding(db)
    port = _finding(db, "port", "tcp-8443", summary={"port": 8443})
    lost = _finding(db, "lost", "lost")
    dismissed = _finding(db, "nginx", "nginx.service", status="dismissed", summary={})
    elsewhere = _finding(db, server_id="srv-2")

    results, failed = adopt_all(db, "srv-1", catalog=V1, now=NOW)

    assert [r.finding.id for r in results] == [project.id, port.id]
    assert failed == [{"findingId": lost.id, "reason": "Module is no longer in the catalog"}]
    assert [f.status for f in (project, port, lost, dismissed, elsewhere)] == [
        "adopted",
        "adopted",
        "open",
        "dismissed",
        "open",
    ]
    assert len(actions) == 3


def test_dismiss(db):
    finding = _finding(db)

    assert dismiss(db, finding.id, now=NOW) is finding
    assert (finding.status, finding.decided_at) == ("dismissed", NOW)


# --- following the catalog at start-up ---------------------------------------------


def _adopted(db, actions):
    _inventory(db)
    finding = _finding(db)
    adopt(db, finding.id, catalog=V1, now=NOW)
    actions.clear()
    return finding


def test_a_check_the_update_added_starts_silent(db, actions):
    finding = _adopted(db, actions)

    assert sync_catalog(db, catalog=WITH_HEALTH) == 1

    health = _checks(db, finding)["health"]
    assert (health.enabled, health.silent) == (True, True)
    assert db.get(MonitorState, health.id).status == "pending"
    assert (finding.kind, finding.status, finding.decided_at, finding.catalog_version) == (
        "changed",
        "open",
        None,
        WITH_HEALTH.version,
    )
    assert actions == []  # load_all_checks schedules it after the sync

    # Adopting the change makes it alert.
    result = adopt(db, finding.id, catalog=WITH_HEALTH, now=NOW)

    assert health.silent is False
    assert health.id in result.enabled


def test_a_dropped_check_stays_and_reopens(db, actions):
    finding = _adopted(db, actions)

    assert sync_catalog(db, catalog=WITHOUT_BROKER) == 1

    broker = _checks(db, finding)["broker"]
    assert (broker.enabled, broker.silent) == (True, False)
    assert (finding.kind, finding.status) == ("changed", "open")

    # Adopting leaves it as the admin had it.
    result = adopt(db, finding.id, catalog=WITHOUT_BROKER, now=NOW)

    assert broker.enabled is True
    assert broker.id not in result.enabled


def test_a_dropped_check_the_admin_switched_off_does_not_reopen(db, actions):
    finding = _adopted(db, actions)
    _checks(db, finding)["broker"].enabled = False
    db.commit()

    assert sync_catalog(db, catalog=WITHOUT_BROKER) == 0
    assert (finding.status, finding.catalog_version) == ("adopted", WITHOUT_BROKER.version)


@pytest.mark.parametrize(
    "catalog",
    [pytest.param(REWORDED, id="reworded"), pytest.param(UNBINDABLE_ADDED, id="unbindable")],
)
def test_an_update_that_changes_nothing_here_only_moves_the_version(db, actions, catalog):
    finding = _adopted(db, actions)

    assert sync_catalog(db, catalog=catalog) == 0

    assert set(_checks(db, finding)) == {"web", "broker"}
    assert (finding.kind, finding.status, finding.catalog_version) == (
        "new",
        "adopted",
        catalog.version,
    )


def test_the_same_catalog_changes_nothing(db, actions):
    finding = _adopted(db, actions)

    assert sync_catalog(db, catalog=V1) == 0
    assert (finding.status, finding.decided_at) == ("adopted", NOW)


def test_a_module_the_catalog_lost_is_left_alone(db, actions):
    finding = _adopted(db, actions)

    assert sync_catalog(db, catalog=NO_PAPERLESS) == 0
    assert all(row.enabled for row in _checks(db, finding).values())
    assert (finding.status, finding.catalog_version) == ("adopted", V1.version)


@pytest.mark.parametrize(
    ("kind", "status"),
    [("new", "open"), ("new", "dismissed"), ("gone", "adopted")],
)
def test_only_adopted_instances_follow_the_catalog(db, actions, kind, status):
    finding = _finding(db, kind=kind, status=status)

    assert sync_catalog(db, catalog=WITH_HEALTH) == 0
    assert db.query(MonitorCheck).count() == 0
    assert (finding.kind, finding.status, finding.catalog_version) == (kind, status, "before")


# --- an adopted instance back from "gone" -------------------------------------------


def _scan(db, hours, catalog, containers=CONTAINERS):
    block = {
        "ts": 1762700000,
        "duration_ms": 900,
        "partial": False,
        "units": [],
        "sockets": [],
        "containers": containers,
        "markers": {},
        "ports": [],
    }
    assert apply_discovery(db, "srv-1", block, catalog=catalog, now=NOW + timedelta(hours=hours))


def _found_and_adopted(db):
    _scan(db, 0, V1)
    finding = db.query(MonitorFinding).one()
    adopt(db, finding.id, catalog=V1, now=NOW)
    return finding


def _missed_twice(db, finding, catalog):
    _scan(db, 1, catalog, containers=[])
    _scan(db, 2, catalog, containers=[])
    assert (finding.kind, finding.status) == ("gone", "open")


def test_back_from_gone_under_the_same_catalog_is_adopted_again(db, actions):
    finding = _found_and_adopted(db)
    _missed_twice(db, finding, V1)

    _scan(db, 3, V1)

    assert (finding.kind, finding.status, finding.catalog_version) == ("new", "adopted", V1.version)


def test_back_from_gone_after_a_catalog_update_waits_for_the_admin(db, actions):
    finding = _found_and_adopted(db)
    _missed_twice(db, finding, V1)
    # The service restarts with a newer catalog while the finding is open: the sync skips it.
    assert sync_catalog(db, catalog=WITH_HEALTH) == 0

    _scan(db, 3, WITH_HEALTH)

    assert (finding.kind, finding.status, finding.decided_at, finding.catalog_version) == (
        "changed",
        "open",
        None,
        V1.version,
    )
    assert "health" not in _checks(db, finding)

    adopt(db, finding.id, catalog=WITH_HEALTH, now=NOW)

    health = _checks(db, finding)["health"]
    assert (health.enabled, health.silent) == (True, False)
    assert finding.catalog_version == WITH_HEALTH.version


def test_back_from_gone_with_a_silent_check_waits_for_the_admin(db, actions):
    finding = _found_and_adopted(db)
    assert sync_catalog(db, catalog=WITH_HEALTH) == 1
    _missed_twice(db, finding, WITH_HEALTH)

    _scan(db, 3, WITH_HEALTH)

    assert (finding.kind, finding.status) == ("changed", "open")
    health = _checks(db, finding)["health"]
    assert health.silent is True

    adopt(db, finding.id, catalog=WITH_HEALTH, now=NOW)

    assert health.silent is False
