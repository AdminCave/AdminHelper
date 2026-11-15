# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module nextcloud-aio (R-1383): the mastercontainer of Nextcloud All-in-One under
either image is an instance of its own and gets its container check and the view nextcloud_aio
every five minutes; a stopped container outside a backup is critical, a backup of more than six
hours warns, a backup with its stopped containers is ok; the containers of AIO and the official
image stay apart, and the module nextcloud still takes no image of AIO."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["nextcloud-aio"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
MASTER = "nextcloud-aio-mastercontainer"
IMAGE = "ghcr.io/nextcloud-releases/all-in-one:latest"


def _container(name, image):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": "",
        "compose_service": "",
        "state": "running",
        "health": "healthy",
        "ports": [],
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
    _container("nextcloud-aio-apache", "ghcr.io/nextcloud-releases/aio-apache:latest"),
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


def _status(check_key, values, status="ok", error=""):
    config, why = probe_config(MODULE, CHECKS[check_key], MASTER, _found(_block(AIO))[MASTER], AIO)
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert MODULE.version == 1
    assert list(CHECKS) == ["master", "aio"]
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
    assert _bind(block, MASTER) == {"master": target, "aio": target}


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
        ("master", "state", "Mastercontainer"),
        ("aio", "stopped", "Stopped containers"),
        ("aio", "backup", "Backup running"),
    ]
