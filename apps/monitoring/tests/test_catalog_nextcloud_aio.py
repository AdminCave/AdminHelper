# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module nextcloud-aio (R-1383): the mastercontainer of Nextcloud All-in-One under
either image is an instance of its own and gets its container check and the view nextcloud_aio
every five minutes; a stopped container outside a backup is critical, a backup of more than six
hours warns, a backup with its stopped containers is ok; the containers of AIO and the official
image stay apart, and the module nextcloud still takes no image of AIO. Version 2 asks status.php
at the apache container and rests that check as a whole while a backup runs (R-1825)."""

import copy
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app import module_sync
from app.catalog.loader import load_catalog
from app.catalog.modules.nextcloud_aio import MODULE as RAW
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.models import MonitorDiscovery, MonitorFinding
from app.module_sync import adopt, probe_config, sync_catalog

CATALOG = load_catalog()
MODULE = CATALOG.modules["nextcloud-aio"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
MASTER = "nextcloud-aio-mastercontainer"
APACHE = "nextcloud-aio-apache"
IMAGE = "ghcr.io/nextcloud-releases/all-in-one:latest"


def _container(name, image, ports=()):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": "",
        "compose_service": "",
        "state": "running",
        "health": "healthy",
        "ports": [{"private": p, "public": None, "proto": "tcp"} for p in ports],
        "mounts": [],
    }


def _block(containers):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": [],
        "sockets": [],
        "containers": list(containers),
        "markers": {},
        "ports": [],
    }


# The mastercontainer with the containers it runs, as AIO names them.
AIO = [
    _container(MASTER, IMAGE),
    _container(APACHE, "ghcr.io/nextcloud-releases/aio-apache:latest"),
    _container("nextcloud-aio-nextcloud", "ghcr.io/nextcloud-releases/aio-nextcloud:latest"),
    _container("nextcloud-aio-database", "ghcr.io/nextcloud-releases/aio-postgresql:latest"),
]


def _found(block, module="nextcloud-aio"):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == module}


def _bind(block, key):
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = config["target"] if config else why
    return bound


def _rated(check_key, values, status="ok", error="", siblings=None):
    config, why = probe_config(MODULE, CHECKS[check_key], MASTER, _found(_block(AIO))[MASTER], AIO)
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    config = {**config, "_check_id": "chk"}
    if siblings is not None:
        config["_siblings"] = siblings
    return ProbeChecker().evaluate(config, report)


def _status(check_key, values, status="ok", error=""):
    return _rated(check_key, values, status, error)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert MODULE.version == 2
    assert list(CHECKS) == ["master", "aio", "status"]
    assert MODULE.detect.container_images == [
        "ghcr.io/nextcloud-releases/all-in-one",
        "nextcloud/all-in-one",
    ]
    assert (MODULE.detect.units, MODULE.detect.processes) == ([], [])
    assert all(c.credential is None for c in MODULE.checks)


@pytest.mark.parametrize(
    "image",
    [
        IMAGE,
        "ghcr.io/nextcloud-releases/all-in-one:beta",
        "nextcloud/all-in-one:latest",
        "docker.io/nextcloud/all-in-one@sha256:" + "a" * 64,
    ],
)
def test_the_mastercontainer_is_the_instance_and_gets_both_checks(image):
    block = _block([_container(MASTER, image), *AIO[1:]])
    assert list(_found(block)) == [MASTER]
    target = {"kind": "container", "name": MASTER, "port_hint": None, "scheme": None}
    apache = {"kind": "container", "name": APACHE, "port_hint": 8000, "scheme": "http"}
    assert _bind(block, MASTER) == {"master": target, "aio": target, "status": apache}


def test_the_containers_of_aio_and_the_official_image_stay_apart():
    # Neither the containers of AIO nor the official image make an instance of AIO; the module
    # nextcloud keeps its no to the images of AIO.
    block = _block([*AIO[1:], _container("cloud-app-1", "nextcloud:31-apache")])
    assert _found(block) == {}
    assert _found(_block(AIO), "nextcloud") == {}


def test_the_view_is_read_at_the_mastercontainer_every_five_minutes():
    check = CHECKS["aio"]
    assert (check.sensor, check.params) == ("app", {"view": "nextcloud_aio"})
    assert check.fields == ["containers", "stopped", "backup", "backup_age_s"]
    assert (check.interval, check.test_object, check.credential) == (300, False, None)
    assert CHECKS["master"].interval == 300


def _aio(containers, stopped, backup, age):
    return {"containers": containers, "stopped": stopped, "backup": backup, "backup_age_s": age}


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        (_aio(5, 0, False, 0), "ok", "", "ok"),
        (_aio(5, 1, False, 0), "ok", "", "critical"),
        # The agent counts no stopped container while the backup stops them.
        (_aio(5, 0, True, 1800), "ok", "", "ok"),
        (_aio(5, 0, True, 21600), "ok", "", "ok"),
        (_aio(5, 0, True, 21601), "ok", "", "warning"),
        # A backup from the interface has no marker and no age.
        (_aio(5, 0, True, 0), "ok", "", "ok"),
        ({}, "error", "the mastercontainer is not running", "critical"),
        ({}, "unsupported", "the root of a container cannot be opened here", "unknown"),
    ],
)
def test_a_stopped_container_is_critical_and_a_long_backup_warns(values, status, error, want):
    assert _status("aio", values, status, error) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ({"state": "exited", "health": "", "restarts": 0}, "critical"),
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
    ],
)
def test_the_mastercontainer_is_critical_when_it_stops_or_is_unhealthy(values, want):
    assert _status("master", values) == want


def test_the_card_shows_the_mastercontainer_the_stopped_containers_and_the_backup():
    assert [(i.check_key, i.field, i.label) for i in MODULE.card] == [
        ("status", "data.versionstring", "Version"),
        ("master", "state", "Mastercontainer"),
        ("aio", "stopped", "Stopped containers"),
        ("aio", "backup", "Backup running"),
    ]


# --- status.php at the apache container (R-1825) ---


def test_status_php_is_asked_at_the_apache_container_as_in_the_module_nextcloud():
    check = CHECKS["status"]
    nextcloud = {c.key: c for c in CATALOG.modules["nextcloud"].checks}["status"]
    assert check.sensor == "http"
    assert (check.target.kind, check.target.container) == ("container", APACHE)
    assert (check.target.port_hint, check.target.scheme) == (8000, "http")
    assert (check.params, check.fields, check.rules) == (
        nextcloud.params,
        nextcloud.fields,
        nextcloud.rules,
    )
    assert (check.params["path"], check.params["host"]) == ("/status.php", "localhost")
    assert check.interval == CHECKS["aio"].interval == 300
    when = check.when
    assert (when.check, when.field, when.op, when.value, when.max_age) == (
        "aio",
        "backup",
        "eq",
        False,
        None,
    )


@pytest.mark.parametrize(
    ("apache", "why"),
    [
        (None, f"no container {APACHE} on this host"),
        ((80,), f"container {APACHE} has no port 8000"),
    ],
)
def test_without_the_apache_container_on_its_port_the_status_check_is_left_out(apache, why):
    others = [AIO[0], *AIO[2:]]
    block = _block(
        others if apache is None else [*others, _container(APACHE, AIO[1]["image"], apache)]
    )
    bound = _bind(block, MASTER)
    assert bound["status"] == why
    assert bound["master"]["name"] == bound["aio"]["name"] == MASTER


def _backup(backup, age=60):
    return {"aio": {"values": {"backup": backup}, "measured_ts": T0 - age, "interval_s": 300}}


_UP = {
    "status_code": 200,
    "data.installed": True,
    "data.maintenance": False,
    "data.needsDbUpgrade": False,
    "data.versionstring": "31.0.9",
}


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        (_UP, "ok", "", "ok"),
        ({**_UP, "status_code": 503}, "ok", "", "critical"),
        ({**_UP, "data.maintenance": True}, "ok", "", "warning"),
        ({**_UP, "data.needsDbUpgrade": True}, "ok", "", "warning"),
        ({}, "error", "connection refused", "critical"),
    ],
)
def test_status_php_rates_outside_a_backup(values, status, error, want):
    assert _rated("status", values, status, error, _backup(False))[0] == want


@pytest.mark.parametrize(
    "siblings",
    [None, {}, _backup(None), _backup(True, age=901)],
    ids=["not-read", "no-sibling", "null", "stale"],
)
def test_status_php_rates_when_the_backup_field_cannot_tell(siblings):
    assert _rated("status", {}, "error", "connection refused", siblings)[:2] == (
        "critical",
        "Probe failed: connection refused",
    )


def test_status_php_rests_while_a_backup_runs():
    status, message, details = _rated("status", {}, "error", "connection refused", _backup(True))

    assert (status, message) == (
        "ok",
        "Resting (aio.backup = true): Probe failed: connection refused",
    )
    when = {"check": "aio", "field": "backup", "op": "eq", "value": False}
    assert [r["key"] for r in details["_details"]["resting"]] == [
        "status_code.critical",
        "data.maintenance.warning",
        "data.needsDbUpgrade.warning",
    ]
    assert all(r["when"] == when for r in details["_details"]["resting"])


# --- an instance adopted under version 1 ---


@pytest.fixture()
def db(db_engine):
    session = sessionmaker(bind=db_engine)()
    yield session
    session.close()


def _v1():
    raw = copy.deepcopy(RAW)
    raw["version"] = 1
    raw["checks"] = [c for c in raw["checks"] if c["key"] != "status"]
    raw["card"] = [i for i in raw["card"] if i["check_key"] != "status"]
    return load_catalog([(raw["id"], raw)])


@pytest.mark.parametrize("with_apache", [True, False], ids=["apache", "no-apache"])
def test_an_adopted_instance_gets_the_status_check_silent(db, monkeypatch, with_apache):
    monkeypatch.setattr(module_sync, "apply_scheduler_actions", lambda actions: None)
    containers = AIO if with_apache else [c for c in AIO if c["name"] != APACHE]
    db.add(MonitorDiscovery(server_id="srv-1", inventory=json.dumps({"containers": containers})))
    finding = MonitorFinding(
        id="f-aio",
        server_id="srv-1",
        module_id="nextcloud-aio",
        instance_key=MASTER,
        kind="new",
        status="open",
        summary=json.dumps(_found(_block(containers))[MASTER]),
        catalog_version="before",
    )
    db.add(finding)
    db.commit()
    v1 = _v1()
    assert v1.errors == ()
    adopt(db, finding.id, catalog=v1)

    assert sync_catalog(db, catalog=CATALOG) == (1 if with_apache else 0)

    checks = {row.module_check_key: row for row in module_sync.instance_checks(db, finding)}
    if not with_apache:
        assert set(checks) == {"master", "aio"}
        assert (finding.kind, finding.status) == ("new", "adopted")
        return
    status = checks["status"]
    config = json.loads(status.config)
    assert (status.enabled, status.silent) == (True, True)
    # The push finds the sibling at the same instance (_probe_siblings).
    assert status.module_instance == checks["aio"].module_instance == MASTER
    assert config["target"]["name"] == APACHE
    assert config["when"] == {"check": "aio", "field": "backup", "op": "eq", "value": False}
    assert (finding.kind, finding.status, finding.catalog_version) == (
        "changed",
        "open",
        CATALOG.version,
    )
