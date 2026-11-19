# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Taking over findings (R-1223): adopting binds the module's catalog checks to the
instance or switches them on, adopting "gone" switches them off and nothing is ever
deleted; at start-up a changed catalog adds its new checks silent to adopted instances
and reopens the finding, a dropped check stays; an adopted instance back from "gone"
after a catalog update waits for the admin."""

import copy
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import module_sync
from app.catalog.loader import load_catalog
from app.catalog.modules.bigbluebutton import MODULE as BBB_MODULE
from app.catalog.modules.openldap import MODULE as LDAP_MODULE
from app.catalog.modules.port import MODULE as PORT_MODULE
from app.catalog.modules.wordpress import MODULE as WP_MODULE
from app.check_configs import ProbeConfig
from app.discovery import MAX_CONTAINER_PORTS, apply_discovery
from app.models import (
    Base,
    MonitorCheck,
    MonitorDiscovery,
    MonitorFinding,
    MonitorModuleTombstone,
    MonitorState,
)
from app.module_plan import build_plan
from app.module_sync import (
    AdoptError,
    adopt,
    adopt_all,
    definition_hash,
    dismiss,
    mark_module_overrides,
    probe_config,
    sync_catalog,
    tombstone_module_check,
)
from app.server_cleanup import cleanup_server

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
WEB_CHANGED = load_catalog(
    [
        _paperless({**WEB, "params": {"path": "/api/v2/"}}, BROKER, SCHED),
        NGINX,
        ("port", PORT_MODULE),
    ]
)
# The new definition asks for a service the project does not have: it cannot bind.
WEB_UNBINDABLE = load_catalog(
    [
        _paperless({**WEB, "target": {**WEB["target"], "service": "missing"}}, BROKER, SCHED),
        NGINX,
        ("port", PORT_MODULE),
    ]
)


def test_test_catalogs_are_valid():
    catalogs = (
        V1,
        WITH_HEALTH,
        WITHOUT_BROKER,
        UNBINDABLE_ADDED,
        REWORDED,
        NO_PAPERLESS,
        WEB_CHANGED,
        WEB_UNBINDABLE,
    )
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


def test_a_bound_check_keeps_its_credential_optional():
    web = {**WEB, "credential": {"slot": "api", "use": "bearer", "optional": True}}
    catalog = load_catalog([_paperless(web, BROKER, SCHED), NGINX, ("port", PORT_MODULE)])
    config, reason = _bind("paperless", "paperless", "web", PROJECT_SUMMARY, catalog=catalog)

    assert reason is None
    assert config["credential"] == {
        "ref": "paperless/paperless/api",
        "use": "bearer",
        "optional": True,
    }
    assert ProbeConfig.model_validate(config).credential.optional is True


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


@pytest.mark.parametrize(
    ("ports", "listening", "reason"),
    [
        # The port listens in the container's network but is not exposed (OnlyOffice's 8000).
        pytest.param(_tcp(80, 443), [80, 443, 8000], None, id="listening-only"),
        pytest.param(_tcp(8000), [80, 443],
                     "container paperless-web-1 has no port 8000", id="exposed-not-listening"),
        pytest.param(_tcp(80), [80], "container paperless-web-1 has no port 8000", id="neither"),
        # Nothing listens yet (or the scan saw no port): the agent decides.
        pytest.param(_tcp(80), [], None, id="nothing-listens"),
        # An older agent or a container whose network the scan could not read.
        pytest.param(_tcp(80), None, "container paperless-web-1 has no port 8000", id="unknown"),
    ],
)  # fmt: skip
def test_the_listening_ports_decide_before_the_exposed_ones(ports, listening, reason):
    web = {**CONTAINERS[0], "ports": ports, "listening": listening}

    config, why = _bind("paperless", "paperless", "web", PROJECT_SUMMARY, [web, *CONTAINERS[1:]])

    assert why == reason
    assert (config is None) == (reason is not None)


@pytest.mark.parametrize(
    ("count", "reason"),
    [
        # A full list may be cut (agent and server keep MAX_CONTAINER_PORTS, lowest first):
        # 8000 may lie beyond the cut, so the agent decides.
        pytest.param(MAX_CONTAINER_PORTS, None, id="full-list-unknown"),
        pytest.param(MAX_CONTAINER_PORTS - 1, "container paperless-web-1 has no port 8000",
                     id="shorter-list-is-whole"),
    ],
)  # fmt: skip
def test_an_exposed_list_at_the_cap_counts_as_unknown(count, reason):
    web = {**CONTAINERS[0], "ports": _tcp(*range(1, count + 1)), "listening": None}

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


def test_adopting_gone_leaves_the_all_clear_to_the_bell_catch_up(db, actions):
    # A switched-off check whose alarm the bell shows lags: the job sends the
    # all-clear (R-1601), as for a check switched off by hand.
    from app.bell_catch_up import lag_target
    from app.models import MonitorState

    _inventory(db)
    finding = _finding(db)
    adopt(db, finding.id, catalog=V1, now=NOW)
    web = _checks(db, finding)["web"]
    state = db.get(MonitorState, web.id) or MonitorState(check_id=web.id, status="critical")
    state.notified_status = state.hub_status = "critical"
    db.merge(state)
    db.commit()
    _reopen(db, finding, "gone")

    adopt(db, finding.id, catalog=V1, now=NOW)

    assert not web.enabled
    assert lag_target(web, db.get(MonitorState, web.id)) == "ok"


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


def test_adopting_new_leaves_off_a_check_the_admin_switched_off(db, actions):
    # Only the checks "gone" switched off come back on; the admin's own switch stays (R-1573).
    _inventory(db)
    finding = _finding(db)
    adopt(db, finding.id, catalog=V1, now=NOW)
    checks = _checks(db, finding)
    checks["broker"].enabled = False
    mark_module_overrides(checks["broker"], enabled=False)
    _reopen(db, finding, "gone")
    adopt(db, finding.id, catalog=V1, now=NOW)
    _reopen(db, finding, "new")

    result = adopt(db, finding.id, catalog=V1, now=NOW)

    assert (checks["web"].enabled, checks["broker"].enabled) == (True, False)
    assert result.enabled == [checks["web"].id]


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


# --- the app checks of R-1404 on instances adopted before them -------------------------

APP_CHECKS = {
    "bigbluebutton": {"meetings", "recordings"},
    "openldap": {"replication"},
    "wordpress": {"version"},
}
SHIPPED = load_catalog()


def _before_app_checks(module):
    """The catalog holding the module as an instance adopted before R-1404 knows it: version 1, without the
    checks (and their card items) that APP_CHECKS lists for it."""
    raw = copy.deepcopy(module)
    added = APP_CHECKS[raw["id"]]
    raw["version"] = 1
    raw["checks"] = [c for c in raw["checks"] if c["key"] not in added]
    raw["card"] = [i for i in raw["card"] if i["check_key"] not in added]
    return load_catalog([(raw["id"], raw)])


@pytest.mark.parametrize(
    ("module", "key", "summary", "containers", "added"),
    [
        (
            BBB_MODULE,
            "bbb-web.service",
            {"unit": "bbb-web.service"},
            [],
            {"meetings", "recordings"},
        ),
        (LDAP_MODULE, "openldap", {"matched_by": ["unit:slapd.service"]}, [], {"replication"}),
        (
            WP_MODULE,
            "blog",
            {"services": {"db": "mariadb", "wordpress": "wordpress"}},
            [
                _container(
                    "blog-wordpress-1", "wordpress:6.8.3-php8.3-apache", "blog", "wordpress"
                ),
                _container("blog-db-1", "mariadb:11", "blog", "db"),
            ],
            {"version"},
        ),
        # slapd in its container: the replication asks a unit, which the instance lacks.
        (
            LDAP_MODULE,
            "ldap",
            {"services": {"openldap": "osixia/openldap"}},
            [_container("ldap-openldap-1", "osixia/openldap:1.5.0", "ldap", "openldap")],
            set(),
        ),
    ],
)
def test_the_app_checks_start_silent_on_instances_adopted_before_them(
    db, actions, module, key, summary, containers, added
):
    before = _before_app_checks(module)
    assert before.errors == ()
    _inventory(db, containers)
    finding = _finding(db, module["id"], key, summary=summary)
    adopt(db, finding.id, catalog=before, now=NOW)
    had = set(_checks(db, finding))

    assert sync_catalog(db, catalog=SHIPPED) == (1 if added else 0)

    checks = _checks(db, finding)
    assert set(checks) - had == added
    for check_key in added:
        row = checks[check_key]
        assert (row.enabled, row.silent, json.loads(row.config)["sensor"]) == (True, True, "app")
        assert db.get(MonitorState, row.id).status == "pending"
    want = ("changed", "open") if added else ("new", "adopted")
    assert (finding.kind, finding.status, finding.catalog_version) == (*want, SHIPPED.version)


# --- checks bound to an image tag (R-1397) ---------------------------------------------


def _wiki(tag):
    return [_container("docs-wiki-1", "ghcr.io/requarks/wiki:" + tag, "docs", "wiki")]


def test_a_move_to_another_major_changes_the_finding_and_removes_its_tag_check(db, actions):
    _scan(db, 0, SHIPPED, _wiki("2"))
    finding = db.query(MonitorFinding).filter_by(module_id="wikijs").one()
    adopt(db, finding.id, catalog=SHIPPED, now=NOW)
    healthz = _checks(db, finding)["healthz"]
    assert healthz.enabled is True

    # A patch release of the same major changes nothing.
    _scan(db, 1, SHIPPED, _wiki("2.5"))
    assert (finding.kind, finding.status) == ("new", "adopted")

    _scan(db, 2, SHIPPED, _wiki("3"))
    assert (finding.kind, finding.status) == ("changed", "open")
    actions.clear()

    result = adopt(db, finding.id, catalog=SHIPPED, now=NOW)

    checks = _checks(db, finding)
    # Gone, not switched off: only then does a return to a fitting tag bring it back.
    assert "healthz" not in checks
    assert db.get(MonitorCheck, healthz.id) is None
    assert result.disabled == [healthz.id]
    assert result.skipped == [
        {"key": "healthz", "reason": "container docs-wiki-1 runs the tag 3, the check needs 2, 2.*"}
    ]
    assert ("remove", healthz.id, None, None) in actions
    # Wiki.js 3 gets /_ready in its place (R-1445).
    assert set(checks) == {"container", "web", "ready"}
    assert checks["ready"].id in result.enabled
    assert all(row.enabled for row in checks.values())


def test_a_tag_check_comes_back_with_its_tag(db, actions):
    _scan(db, 0, SHIPPED, _wiki("2"))
    finding = db.query(MonitorFinding).filter_by(module_id="wikijs").one()
    adopt(db, finding.id, catalog=SHIPPED, now=NOW)
    _scan(db, 1, SHIPPED, _wiki("3"))
    adopt(db, finding.id, catalog=SHIPPED, now=NOW)

    _scan(db, 2, SHIPPED, _wiki("2.5"))
    assert (finding.kind, finding.status) == ("changed", "open")
    actions.clear()
    result = adopt(db, finding.id, catalog=SHIPPED, now=NOW)

    checks = _checks(db, finding)
    healthz = checks["healthz"]
    assert (healthz.enabled, healthz.silent) == (True, False)
    assert healthz.id in result.enabled
    assert ("add", healthz.id, healthz.interval, "probe") in actions
    assert "ready" not in checks
    assert result.skipped == [
        {"key": "ready", "reason": "container docs-wiki-1 runs the tag 2.5, the check needs 3, 3.*"}
    ]


def test_a_tag_check_is_not_created_for_a_tag_it_does_not_fit(db, actions):
    _scan(db, 0, SHIPPED, _wiki("3"))
    finding = db.query(MonitorFinding).filter_by(module_id="wikijs").one()

    result = adopt(db, finding.id, catalog=SHIPPED, now=NOW)

    assert set(_checks(db, finding)) == {"container", "web", "ready"}
    assert result.skipped == [
        {"key": "healthz", "reason": "container docs-wiki-1 runs the tag 3, the check needs 2, 2.*"}
    ]


def _drop_tag_checks(db, finding):
    """The summary as a monitoring service before R-1397 stored it."""
    summary = json.loads(finding.summary)
    del summary["tag_checks"]
    finding.summary = json.dumps(summary)
    db.commit()


@pytest.mark.parametrize("tag", ["2", "3", "latest"])
@pytest.mark.parametrize("status", ["adopted", "dismissed"])
def test_a_summary_from_before_tag_checks_keeps_the_finding_as_decided(db, actions, tag, status):
    _scan(db, 0, SHIPPED, _wiki(tag))
    finding = db.query(MonitorFinding).filter_by(module_id="wikijs").one()
    if status == "adopted":
        adopt(db, finding.id, catalog=SHIPPED, now=NOW)
    else:
        dismiss(db, finding.id, now=NOW)
    _drop_tag_checks(db, finding)

    _scan(db, 1, SHIPPED, _wiki(tag))

    assert (finding.kind, finding.status) == ("new", status)
    # The scan fills the key in, so the next major is a change again.
    assert "tag_checks" in json.loads(finding.summary)
    _scan(db, 2, SHIPPED, _wiki("3" if tag == "2" else "2"))
    assert (finding.kind, finding.status) == ("changed" if status == "adopted" else "new", "open")


# --- module checks the admin deleted (R-1264) ------------------------------------------


def _delete(db, row):
    tombstone_module_check(db, row)
    db.delete(row)
    db.commit()


def _tombstones(db):
    return {
        (t.server_id, t.module_id, t.instance_key, t.check_key)
        for t in db.query(MonitorModuleTombstone)
    }


def test_a_deleted_module_check_is_not_adopted_again(db, actions):
    finding = _adopted(db, actions)
    _delete(db, _checks(db, finding)["broker"])
    _reopen(db, finding, "changed")

    result = adopt(db, finding.id, catalog=V1, now=NOW)

    assert set(_checks(db, finding)) == {"web"}
    assert result.enabled == [_checks(db, finding)["web"].id]
    assert result.skipped == [{"key": "sched", "reason": "no unit for this instance"}]
    assert _tombstones(db) == {("srv-1", "paperless", "paperless", "broker")}


def test_burying_a_module_check_twice_keeps_one_tombstone(db, actions):
    finding = _adopted(db, actions)
    broker = _checks(db, finding)["broker"]

    tombstone_module_check(db, broker)
    db.commit()
    tombstone_module_check(db, broker)
    db.commit()

    assert db.query(MonitorModuleTombstone).count() == 1


def test_a_check_of_no_module_leaves_no_tombstone(db):
    row = MonitorCheck(id="c-1", server_id="srv-1", name="Ping", check_type="ping", config="{}")
    db.add(row)
    db.commit()

    _delete(db, row)

    assert db.query(MonitorModuleTombstone).count() == 0


def test_the_catalog_sync_does_not_bring_back_a_deleted_check(db, actions):
    finding = _adopted(db, actions)
    _delete(db, _checks(db, finding)["web"])

    # The update adds "health"; "web" stays deleted.
    assert sync_catalog(db, catalog=WITH_HEALTH) == 1

    assert set(_checks(db, finding)) == {"broker", "health"}


def test_a_finding_that_lacks_only_a_deleted_check_does_not_reopen(db, actions):
    finding = _adopted(db, actions)
    db.add(
        MonitorModuleTombstone(
            id="t-1",
            server_id="srv-1",
            module_id="paperless",
            instance_key="paperless",
            check_key="health",
        )
    )
    db.commit()

    assert sync_catalog(db, catalog=WITH_HEALTH) == 0

    assert set(_checks(db, finding)) == {"web", "broker"}
    assert (finding.kind, finding.status, finding.catalog_version) == (
        "new",
        "adopted",
        WITH_HEALTH.version,
    )


@pytest.mark.parametrize(
    ("server_id", "module_id", "instance_key"),
    [
        pytest.param("srv-2", "paperless", "paperless", id="other server"),
        pytest.param("srv-1", "other", "paperless", id="other module"),
        pytest.param("srv-1", "paperless", "other", id="other instance"),
    ],
)
def test_a_tombstone_binds_only_its_own_instance(db, actions, server_id, module_id, instance_key):
    _inventory(db)
    finding = _finding(db)
    db.add(
        MonitorModuleTombstone(
            id="t-1",
            server_id=server_id,
            module_id=module_id,
            instance_key=instance_key,
            check_key="broker",
        )
    )
    db.commit()

    adopt(db, finding.id, catalog=V1, now=NOW)

    assert set(_checks(db, finding)) == {"web", "broker"}


def test_deleting_the_server_takes_its_module_tombstones(db, actions, monkeypatch):
    monkeypatch.setattr("app.server_cleanup.apply_scheduler_actions", lambda _: None)
    finding = _adopted(db, actions)
    _delete(db, _checks(db, finding)["broker"])
    db.add(
        MonitorModuleTombstone(
            id="t-other",
            server_id="srv-2",
            module_id="paperless",
            instance_key="paperless",
            check_key="broker",
        )
    )
    db.commit()

    cleanup_server(db, "srv-1")

    assert _tombstones(db) == {("srv-2", "paperless", "paperless", "broker")}


# --- a changed catalog definition is offered, not rolled out (R-1264) ----------------


def _catalog_check(catalog, key, module_id="paperless"):
    return next(c for c in catalog.modules[module_id].checks if c.key == key)


def test_the_definition_hash_is_stable_and_tells_definitions_apart():
    again = load_catalog([_paperless(WEB, BROKER, SCHED), NGINX, ("port", PORT_MODULE)])
    reordered = load_catalog(
        [("port", PORT_MODULE), NGINX, _paperless(dict(reversed(list(WEB.items()))), BROKER, SCHED)]
    )
    web = definition_hash(_catalog_check(V1, "web"))

    assert definition_hash(_catalog_check(again, "web")) == web
    assert definition_hash(_catalog_check(reordered, "web")) == web
    assert definition_hash(_catalog_check(REWORDED, "web")) == web
    assert definition_hash(_catalog_check(WEB_CHANGED, "web")) != web
    assert definition_hash(_catalog_check(V1, "broker")) != web
    assert web.startswith("sha256:") and len(web) == len("sha256:") + 64


def test_a_bound_check_keeps_the_hash_of_its_definition(db, actions):
    finding = _adopted(db, actions)

    rows = _checks(db, finding)
    assert {key: row.module_check_hash for key, row in rows.items()} == {
        key: definition_hash(_catalog_check(V1, key)) for key in ("web", "broker")
    }


def _admin_edit(row, **parts):
    config = json.loads(row.config)
    config.update(parts)
    row.config = json.dumps(config)
    row.name, row.interval = "Paperless web, mine", "15m"


def test_a_changed_definition_is_offered_and_adopting_writes_it(db, actions):
    finding = _adopted(db, actions)
    web, broker = _checks(db, finding)["web"], _checks(db, finding)["broker"]
    _admin_edit(web, interval_s=900, timeout_s=20)
    db.commit()
    before = web.config

    assert sync_catalog(db, catalog=WEB_CHANGED) == 1

    # Offered: the check keeps running as it was.
    assert (finding.kind, finding.status) == ("changed", "open")
    assert web.config == before
    assert [
        row.id
        for row in module_sync.updatable_checks([web, broker], WEB_CHANGED.modules["paperless"])
    ] == [web.id]

    result = adopt(db, finding.id, catalog=WEB_CHANGED, now=NOW)

    assert result.updated == [web.id]
    assert result.skipped == [{"key": "sched", "reason": "no unit for this instance"}]
    config = json.loads(web.config)
    assert config["params"]["path"] == "/api/v2/"
    # The admin's interval, timeout, name and switches stay.
    assert (config["interval_s"], config["timeout_s"]) == (900, 20)
    assert (web.name, web.interval, web.enabled, web.silent) == (
        "Paperless web, mine",
        "15m",
        True,
        False,
    )
    ProbeConfig.model_validate(config)
    assert web.module_check_hash == definition_hash(_catalog_check(WEB_CHANGED, "web"))
    assert ("add", web.id, "15m", "probe") in actions
    assert module_sync.updatable_checks([web], WEB_CHANGED.modules["paperless"]) == []

    # Nothing is left to offer.
    finding.catalog_version = "older"
    db.commit()
    assert sync_catalog(db, catalog=WEB_CHANGED) == 0


def test_an_admin_edit_is_no_catalog_update(db, actions):
    finding = _adopted(db, actions)
    web = _checks(db, finding)["web"]
    _admin_edit(web, rules=[], interval_s=900)
    db.commit()

    assert sync_catalog(db, catalog=REWORDED) == 0
    assert module_sync.updatable_checks([web], REWORDED.modules["paperless"]) == []
    assert (finding.status, finding.kind) == ("adopted", "new")


def test_a_changed_definition_of_a_switched_off_check_does_not_reopen(db, actions):
    finding = _adopted(db, actions)
    web = _checks(db, finding)["web"]
    web.enabled = False
    db.commit()

    assert sync_catalog(db, catalog=WEB_CHANGED) == 0
    assert (finding.status, finding.catalog_version) == ("adopted", WEB_CHANGED.version)


def test_a_check_bound_before_hashes_gets_todays_without_an_offer(db, actions):
    finding = _adopted(db, actions)
    for row in _checks(db, finding).values():
        row.module_check_hash = None
    db.commit()
    before = _checks(db, finding)["web"].config

    assert sync_catalog(db, catalog=WEB_CHANGED) == 0

    rows = _checks(db, finding)
    assert rows["web"].config == before
    assert {key: row.module_check_hash for key, row in rows.items()} == {
        key: definition_hash(_catalog_check(WEB_CHANGED, key)) for key in ("web", "broker")
    }
    assert finding.status == "adopted"


def test_an_unhashed_check_of_an_unchanged_catalog_gets_its_hash_too(db, actions):
    finding = _adopted(db, actions)
    finding.catalog_version = V1.version
    _checks(db, finding)["web"].module_check_hash = None
    db.commit()

    assert sync_catalog(db, catalog=V1) == 0
    assert _checks(db, finding)["web"].module_check_hash == definition_hash(
        _catalog_check(V1, "web")
    )


def test_an_update_the_admins_timeout_cannot_hold_keeps_the_old_row(db, actions):
    finding = _adopted(db, actions)
    web = _checks(db, finding)["web"]
    # Out of ProbeConfig's range (timeout_s <= 30): the admin's value is carried into the
    # new config, which then fails validation.
    _admin_edit(web, timeout_s=99)
    db.commit()
    before, old_hash = web.config, web.module_check_hash

    assert sync_catalog(db, catalog=WEB_CHANGED) == 1
    result = adopt(db, finding.id, catalog=WEB_CHANGED, now=NOW)

    assert result.updated == []
    assert {"key": "web", "reason": "the updated check does not hold"} in result.skipped
    assert (web.config, web.module_check_hash) == (before, old_hash)


def test_a_new_definition_that_does_not_bind_keeps_the_old_one(db, actions):
    finding = _adopted(db, actions)
    web = _checks(db, finding)["web"]
    before, old_hash = web.config, web.module_check_hash

    assert sync_catalog(db, catalog=WEB_UNBINDABLE) == 1
    result = adopt(db, finding.id, catalog=WEB_UNBINDABLE, now=NOW)

    assert result.updated == []
    (why,) = [skip["reason"] for skip in result.skipped if skip["key"] == "web"]
    assert why == "no container for this instance"
    assert (web.config, web.module_check_hash, web.enabled) == (before, old_hash, True)
    assert web.id in result.enabled


# --- central checks of a vhost (R-1501) ---------------------------------------------

SERVED = {
    "key": "served",
    "name": "Served",
    "sensor": "app",
    "target": {"kind": "vhost"},
    "params": {"view": "web_vhost_cert"},
    "interval": 3600,
    "fields": ["served_days_left"],
}
RESOLVES = {
    "key": "resolves",
    "name": "Resolves",
    "sensor": "dns",
    "central": True,
    "target": {"kind": "vhost"},
    "interval": 900,
}
OUTSIDE = {
    "key": "outside",
    "name": "Outside",
    "sensor": "tls",
    "central": True,
    "target": {"kind": "vhost"},
    "params": {"expiry": False},
    "interval": 3600,
}


def _site(*checks):
    return (
        "site",
        {
            "id": "site",
            "name": "Site",
            "version": 1,
            "instance": "vhost",
            "detect": {"vhost_tls": True},
            "checks": list(checks),
        },
    )


SITE_AGENT = load_catalog([_site(SERVED)])
SITE = load_catalog([_site(SERVED, RESOLVES, OUTSIDE)])
SITE_EXPECTED = load_catalog(
    [_site(SERVED, {**RESOLVES, "params": {"expected": ["192.0.2.10"]}}, OUTSIDE)]
)
SITE_SUMMARY = {"server": "nginx", "port": 8443, "tls": True}


def test_the_site_catalogs_are_valid():
    assert [c.errors for c in (SITE_AGENT, SITE, SITE_EXPECTED)] == [(), (), ()]


def _central(check_key, key="shop.example.org", summary=SITE_SUMMARY):
    check = next(c for c in SITE.modules["site"].checks if c.key == check_key)
    return module_sync.central_config(check, key, summary)


def test_a_central_check_asks_the_vhosts_name_and_the_tls_one_its_port():
    assert _central("resolves") == (
        {"sensor": "dns", "host": "shop.example.org", "params": {}},
        None,
    )
    assert _central("outside") == (
        {"sensor": "tls", "host": "shop.example.org", "params": {"expiry": False}, "port": 8443},
        None,
    )
    assert _central("outside", summary={}) == (None, "no port for this vhost")


@pytest.mark.parametrize(
    "key",
    [
        "localhost",
        "app.localhost",
        "shop.test",
        "shop.example",
        "shop.invalid",
        "nas.local",
        "nas.home.arpa",
        "wiki.internal",
        "wiki.lan",
        "WIKI.HOME.",
        # A single label (Kevin 2026-11-18, R-1548): the search domain makes it local.
        "intranet",
        "intranet.",
    ],
)
def test_a_name_no_public_resolver_answers_gets_no_central_check(key):
    assert _central("resolves", key) == (None, "not a public name")
    assert _central("outside", key) == (None, "not a public name")


@pytest.mark.parametrize("key", ["lan.example.org", "home.example.net", "local-shop.de"])
def test_a_special_word_inside_a_public_name_does_not_hide_it(key):
    config, why = _central("resolves", key)
    assert why is None and config["host"] == key


def _site_finding(db, key="shop.example.org"):
    return _finding(db, "site", key, summary=SITE_SUMMARY)


def test_adopting_a_vhost_creates_its_central_checks(db, actions):
    finding = _site_finding(db)

    result = adopt(db, finding.id, catalog=SITE, now=NOW)

    checks = _checks(db, finding)
    assert {key: row.check_type for key, row in checks.items()} == {
        "served": "probe",
        "resolves": "central",
        "outside": "central",
    }
    assert json.loads(checks["outside"].config) == {
        "sensor": "tls",
        "host": "shop.example.org",
        "params": {"expiry": False},
        "port": 8443,
    }
    assert (checks["resolves"].interval, checks["outside"].interval) == ("15m", "1h")
    assert result.skipped == []
    assert sorted(actions) == sorted(
        [
            ("add", checks["served"].id, "1h", "probe"),
            ("add", checks["resolves"].id, "15m", "central"),
            ("add", checks["outside"].id, "1h", "central"),
        ]
    )
    # The agent's plan carries only its own probe.
    plan = build_plan(db, "srv-1", catalog=SITE, now=NOW)
    assert [p["id"] for p in plan["probes"]] == [checks["served"].id]


def test_adopting_the_real_web_domain_module_binds_its_central_checks(db, actions):
    catalog = load_catalog()
    finding = _finding(db, "web_domain", "shop.example.org", summary=SITE_SUMMARY)

    result = adopt(db, finding.id, catalog=catalog, now=NOW)

    checks = _checks(db, finding)
    assert {key: row.check_type for key, row in checks.items()} == {
        "certificate": "probe",
        "reload": "probe",
        "dns": "central",
        "outside": "central",
    }
    assert json.loads(checks["dns"].config) == {
        "sensor": "dns",
        "host": "shop.example.org",
        "params": {},
    }
    assert json.loads(checks["outside"].config) == {
        "sensor": "tls",
        "host": "shop.example.org",
        "params": {"expiry": False},
        "port": 8443,
    }
    assert result.skipped == []
    # The agent's plan carries only its own probes.
    plan = build_plan(db, "srv-1", catalog=catalog, now=NOW)
    assert {p["id"] for p in plan["probes"]} == {checks["certificate"].id, checks["reload"].id}


def test_adopting_an_internal_name_skips_its_central_checks(db, actions):
    finding = _site_finding(db, "wiki.lan")

    result = adopt(db, finding.id, catalog=SITE, now=NOW)

    assert set(_checks(db, finding)) == {"served"}
    assert result.skipped == [
        {"key": "resolves", "reason": "not a public name"},
        {"key": "outside", "reason": "not a public name"},
    ]


def test_the_catalog_update_adds_the_central_checks_silent(db, actions):
    finding = _site_finding(db)
    adopt(db, finding.id, catalog=SITE_AGENT, now=NOW)
    actions.clear()

    assert sync_catalog(db, catalog=SITE) == 1

    checks = _checks(db, finding)
    assert [(checks[k].check_type, checks[k].silent) for k in ("resolves", "outside")] == [
        ("central", True),
        ("central", True),
    ]
    assert (finding.kind, finding.status) == ("changed", "open")
    assert actions == []

    adopt(db, finding.id, catalog=SITE, now=NOW)

    assert not any(row.silent for row in checks.values())


def test_a_deleted_central_check_is_not_created_again(db, actions):
    finding = _site_finding(db)
    adopt(db, finding.id, catalog=SITE, now=NOW)
    resolves = _checks(db, finding)["resolves"]
    tombstone_module_check(db, resolves)
    db.delete(resolves)
    db.commit()
    _reopen(db, finding, "changed")

    adopt(db, finding.id, catalog=SITE, now=NOW)

    assert set(_checks(db, finding)) == {"served", "outside"}


def test_a_gone_vhost_switches_its_central_checks_off(db, actions):
    finding = _site_finding(db)
    adopt(db, finding.id, catalog=SITE, now=NOW)
    _reopen(db, finding, "gone")
    actions.clear()

    adopt(db, finding.id, catalog=SITE, now=NOW)

    assert not any(row.enabled for row in _checks(db, finding).values())
    assert len(actions) == 3


def test_a_central_check_takes_a_new_definition_and_keeps_interval_and_partner(db, actions):
    finding = _site_finding(db)
    adopt(db, finding.id, catalog=SITE, now=NOW)
    resolves = _checks(db, finding)["resolves"]
    resolves.interval = "1h"
    resolves.config = json.dumps({**json.loads(resolves.config), "pair_check_id": "pair-1"})
    db.commit()
    _reopen(db, finding, "changed")

    result = adopt(db, finding.id, catalog=SITE_EXPECTED, now=NOW)

    assert result.updated == [resolves.id]
    assert resolves.interval == "1h"
    assert json.loads(resolves.config) == {
        "sensor": "dns",
        "host": "shop.example.org",
        "params": {"expected": ["192.0.2.10"]},
        "pair_check_id": "pair-1",
    }


def test_a_check_the_catalog_moved_to_the_service_is_not_rewritten(db, actions):
    finding = _site_finding(db)
    adopt(db, finding.id, catalog=SITE, now=NOW)
    resolves = _checks(db, finding)["resolves"]
    resolves.check_type = "probe"
    before = resolves.config
    db.commit()
    _reopen(db, finding, "changed")

    result = adopt(db, finding.id, catalog=SITE_EXPECTED, now=NOW)

    assert result.updated == []
    assert result.skipped == [
        {
            "key": "resolves",
            "reason": "the catalog moved the check between the agent and the monitoring service",
        }
    ]
    assert resolves.config == before


# --- the admin's own rules and switches (R-1567, R-1573) ----------------------------


def test_a_catalog_update_keeps_the_rules_the_admin_changed(db, actions):
    finding = _adopted(db, actions)
    web = _checks(db, finding)["web"]
    old = web.config
    config = json.loads(old)
    config["rules"] = [{"field": "status_code", "op": "ne", "value": 204, "level": "warning"}]
    web.config = json.dumps(config)
    mark_module_overrides(web, old_config=old)
    db.commit()
    before = web.config

    assert sync_catalog(db, catalog=WEB_CHANGED) == 1
    result = adopt(db, finding.id, catalog=WEB_CHANGED, now=NOW)

    assert result.updated == []
    assert {"key": "web", "reason": "the admin changed the check's rules; they stay"} in (
        result.skipped
    )
    assert web.config == before


@pytest.mark.parametrize(
    ("parts", "marked"),
    [
        pytest.param({"interval_s": 900, "timeout_s": 20}, [], id="interval-timeout"),
        pytest.param({"rules": []}, ["config"], id="rules"),
    ],
)
def test_only_a_change_the_update_would_lose_marks_the_config(db, actions, parts, marked):
    web = _checks(db, _adopted(db, actions))["web"]
    old = web.config
    web.config = json.dumps({**json.loads(old), **parts})

    mark_module_overrides(web, old_config=old)

    assert json.loads(web.overridden_fields) == marked


def test_switching_on_again_drops_the_mark(db, actions):
    web = _checks(db, _adopted(db, actions))["web"]
    mark_module_overrides(web, enabled=False)
    assert json.loads(web.overridden_fields) == ["enabled"]
    mark_module_overrides(web, enabled=True)
    assert json.loads(web.overridden_fields) == []


def test_the_api_marks_the_admins_switch_and_rules_on_a_module_check(client_db, actions):
    client, factory = client_db
    with factory() as db:
        _inventory(db)
        finding = _finding(db)
        adopt(db, finding.id, catalog=V1, now=NOW)
        web = _checks(db, finding)["web"]
        web_id, config = web.id, json.loads(web.config)

    assert client.post(f"/checks/{web_id}/toggle").json()["overriddenFields"] == ["enabled"]
    assert client.post(f"/checks/{web_id}/toggle").json()["overriddenFields"] == []
    r = client.put(f"/checks/{web_id}", json={"config": {**config, "interval_s": 900}})
    assert r.json()["overriddenFields"] == []
    r = client.put(f"/checks/{web_id}", json={"config": {**config, "rules": []}, "enabled": False})
    assert r.json()["overriddenFields"] == ["config", "enabled"]


# --- a check of one instance, ports chosen at the host (R-1528) ---------------------

_PBX_WEB = {
    "key": "web",
    "name": "Web interface",
    "sensor": "http",
    "target": {
        "kind": "loopback",
        "alternatives": [
            {"port_hint": 443, "scheme": "https"},
            {"port_hint": 5001, "scheme": "https"},
        ],
    },
    "params": {"path": "/"},
    "interval": 300,
    "fields": ["status_code"],
    "instance": "pbx.service",
}
_PBX_SERVICE = {
    "key": "service",
    "name": "Service",
    "sensor": "unit",
    "target": {"kind": "unit"},
    "params": {},
    "interval": 300,
    "fields": ["sub_state"],
}


def _pbx(web=_PBX_WEB):
    raw = {
        "id": "pbx",
        "name": "PBX",
        "version": 1,
        "instance": "unit",
        "detect": {"units": ["pbx.service", "pbx-mc01.service"]},
        "checks": [web, _PBX_SERVICE],
    }
    catalog = load_catalog([("pbx", raw)])
    assert catalog.errors == ()
    return catalog


PBX = _pbx()


def _socket(port, *, container="", unit="", proto="tcp"):
    return {
        "proto": proto,
        "addr": "0.0.0.0",
        "port": port,
        "process": "p",
        "container": container,
        "unit": unit,
    }


def _scanned(db, sockets, *, whole=True):
    inventory = {"containers": [], "sockets": sockets, "complete": {"sockets": whole}}
    db.add(MonitorDiscovery(server_id="srv-1", inventory=json.dumps(inventory)))
    db.commit()


def test_a_check_naming_an_instance_is_bound_there_only(db, actions):
    _scanned(db, [_socket(443)])
    main = _finding(db, "pbx", "pbx.service", summary={})
    other = _finding(db, "pbx", "pbx-mc01.service", summary={})

    adopt(db, main.id, catalog=PBX, now=NOW)
    result = adopt(db, other.id, catalog=PBX, now=NOW)

    assert set(_checks(db, main)) == {"web", "service"}
    # The other instance skips the check without a reason: it is not its check.
    assert set(_checks(db, other)) == {"service"}
    assert result.skipped == []


def test_a_resync_binds_a_check_naming_an_instance_there_only(db, actions):
    _scanned(db, [_socket(443)])
    main = _finding(db, "pbx", "pbx.service", summary={})
    other = _finding(db, "pbx", "pbx-mc01.service", summary={})
    without_web = _pbx(web={**_PBX_SERVICE, "key": "service2"})
    adopt(db, main.id, catalog=without_web, now=NOW)
    adopt(db, other.id, catalog=without_web, now=NOW)

    sync_catalog(db, catalog=_pbx(web={**_PBX_WEB, "name": "Web"}))

    assert "web" in _checks(db, main)
    assert "web" not in _checks(db, other)


@pytest.mark.parametrize(
    ("kind", "sockets", "port", "reason"),
    [
        pytest.param("loopback", None, 443, None, id="loopback-unknown-first"),
        pytest.param("loopback", [_socket(5001)], 5001, None, id="loopback-seen"),
        pytest.param("loopback", [_socket(443), _socket(5001)], 443, None, id="loopback-order"),
        pytest.param(
            "loopback",
            [_socket(443, container="web-1"), _socket(5001)],
            5001,
            None,
            id="loopback-not-a-container",
        ),
        pytest.param(
            "loopback",
            [_socket(443, proto="udp")],
            None,
            "the host listens on none of the ports 443, 5001",
            id="loopback-udp",
        ),
        pytest.param(
            "loopback",
            [],
            None,
            "the host listens on none of the ports 443, 5001",
            id="loopback-none",
        ),
        pytest.param("unit", None, 443, None, id="unit-unknown-first"),
        pytest.param("unit", [_socket(5001, unit="pbx.service")], 5001, None, id="unit-seen"),
        pytest.param(
            "unit",
            [_socket(443, unit="other.service"), _socket(5001, unit="pbx.service")],
            5001,
            None,
            id="unit-its-own",
        ),
        # An agent that does not tell the unit: the agent asks the first.
        pytest.param("unit", [_socket(5001)], 443, None, id="unit-older-agent"),
        pytest.param(
            "unit",
            [_socket(5001, unit="other.service")],
            None,
            "unit pbx.service listens on none of the ports 443, 5001",
            id="unit-none",
        ),
    ],
)
def test_the_host_sockets_pick_the_alternative(kind, sockets, port, reason):
    catalog = _pbx(web={**_PBX_WEB, "target": {**_PBX_WEB["target"], "kind": kind}})
    module = catalog.modules["pbx"]
    check = module.checks[0]
    config, why = probe_config(module, check, "pbx.service", {}, [], sockets)
    assert why == reason
    assert (config["target"]["port_hint"] if config else None) == port


@pytest.mark.parametrize(("whole", "port"), [(True, 5001), (False, 443)])
def test_adopting_reads_the_sockets_only_when_the_scan_saw_them_whole(db, actions, whole, port):
    _scanned(db, [_socket(5001)], whole=whole)
    finding = _finding(db, "pbx", "pbx.service", summary={})

    adopt(db, finding.id, catalog=PBX, now=NOW)

    assert json.loads(_checks(db, finding)["web"].config)["target"]["port_hint"] == port
