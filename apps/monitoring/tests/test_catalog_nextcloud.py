# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module nextcloud (R-1241): the official image and the snap are found, the
container checks bind to the compose services app and cron, the status check to app only
where it serves HTTP, the snap's unit check only to the snap, and each rule fires on its
value and not on the one beside it."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["nextcloud"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
SNAP_UNIT = "snap.nextcloud.apache.service"


def _block(containers=(), units=()):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": list(units),
        "sockets": [],
        "containers": list(containers),
        "markers": {},
        "ports": [],
    }


def _container(name, image, project="", service="", ports=()):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": "",
        "ports": [{"private": p, "public": None, "proto": "tcp"} for p in ports],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


def _found(block):
    """The nextcloud instances in the block: key → summary."""
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "nextcloud"
    }


def _bind(block, key):
    """check key → (target name, None) or (None, why) for the instance `key` of the block."""
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _status(check_key, **values):
    """The status the probe checker gives a result of the bound check with these values."""
    if check_key != "snap":
        block, key = _block(COMPOSE), "cloud"
    else:
        block, key = _block(units=[_unit(SNAP_UNIT)]), "nextcloud"
    config, why = probe_config(MODULE, CHECKS[check_key], key, _found(block)[key], COMPOSE)
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


COMPOSE = [
    _container("cloud-app-1", "nextcloud:30-apache", "cloud", "app", ports=[80]),
    _container("cloud-cron-1", "nextcloud:30-apache", "cloud", "cron", ports=[80]),
    _container("cloud-db-1", "mariadb:11", "cloud", "db", ports=[3306]),
    _container("cloud-redis-1", "redis:alpine", "cloud", "redis", ports=[6379]),
]


def test_the_module_loads_with_container_status_and_snap_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["app", "cron", "status", "snap"]
    assert CHECKS["status"].params == {"path": "/status.php", "method": "GET", "host": "localhost"}
    assert (CHECKS["status"].interval, CHECKS["status"].test_object) == (300, False)


def test_a_compose_project_binds_both_containers_and_status_to_app_only():
    assert _found(_block(COMPOSE)) == {
        "cloud": {
            "services": {
                "app": "nextcloud",
                "cron": "nextcloud",
                "db": "mariadb",
                "redis": "redis",
            }
        }
    }
    assert _bind(_block(COMPOSE), "cloud") == {
        "app": ("cloud-app-1", None),
        "cron": ("cloud-cron-1", None),
        "status": ("cloud-app-1", None),
        "snap": (None, "no unit for this instance"),
    }


def test_the_fpm_image_keeps_its_container_check_but_gets_no_http_check():
    """No HTTP check on the FastCGI port; a project without a cron service leaves that
    check unbound."""
    block = _block(
        [
            _container("cloud-app-1", "nextcloud:30-fpm", "cloud", "app", ports=[9000]),
            _container("cloud-web-1", "nginx:alpine", "cloud", "web", ports=[80]),
        ]
    )
    bound = _bind(block, "cloud")
    assert bound["app"] == ("cloud-app-1", None)
    assert bound["cron"] == (None, "no container for this instance")
    assert bound["status"] == (None, "container cloud-app-1 has no port 80")


def test_the_snap_binds_its_unit_and_no_http_check():
    block = _block(units=[_unit(SNAP_UNIT), _unit("snap.nextcloud.php-fpm.service")])
    assert _found(block) == {"nextcloud": {"matched_by": [f"unit:{SNAP_UNIT}"]}}
    assert _bind(block, "nextcloud") == {
        "app": (None, "no container for this instance"),
        "cron": (None, "no container for this instance"),
        "status": (None, "no container for this instance"),
        "snap": (SNAP_UNIT, None),
    }


def test_a_container_outside_compose_is_found_but_gets_no_check():
    block = _block([_container("nextcloud", "nextcloud:latest", ports=[80])])
    assert _bind(block, "nextcloud") == {
        "app": (None, "no container for this instance"),
        "cron": (None, "no container for this instance"),
        "status": (None, "no container for this instance"),
        "snap": (None, "no unit for this instance"),
    }


@pytest.mark.parametrize(
    "image",
    ["nextcloud/aio-nextcloud:latest", "nextcloud/all-in-one:latest", "ghcr.io/x/nextcloud:30"],
)
def test_all_in_one_and_foreign_images_are_not_taken_for_nextcloud(image):
    assert _found(_block([_container("nc", image, "aio", "app", ports=[80])])) == {}


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        (
            "status",
            {"status_code": 200, "data.maintenance": False, "data.needsDbUpgrade": False},
            "ok",
        ),
        (
            "status",
            {"status_code": 200, "data.maintenance": True, "data.needsDbUpgrade": False},
            "warning",
        ),
        (
            "status",
            {"status_code": 200, "data.maintenance": False, "data.needsDbUpgrade": True},
            "warning",
        ),
        # Untrusted host or a broken server: no JSON, the status code alone decides.
        ("status", {"status_code": 400}, "critical"),
        ("status", {"status_code": 503}, "critical"),
        # true is not 1: a value of another type is not the maintenance flag.
        ("status", {"status_code": 200, "data.maintenance": 1, "data.needsDbUpgrade": 0}, "ok"),
        ("app", {"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ("app", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        # A dead cron container stops the background jobs; status.php does not show it.
        ("cron", {"state": "exited", "health": "none", "restarts": 0}, "critical"),
        ("cron", {"state": "running", "health": "none", "restarts": 2}, "ok"),
        ("snap", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("snap", {"active_state": "failed", "sub_state": "failed"}, "critical"),
        ("snap", {"active_state": "activating", "sub_state": "start"}, "critical"),
    ],
)
def test_each_rule_fires_on_its_value(check_key, values, want):
    assert _status(check_key, **values) == want


def test_the_card_shows_version_maintenance_upgrade_containers_and_snap():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("status", "data.versionstring"),
        ("status", "data.maintenance"),
        ("status", "data.needsDbUpgrade"),
        ("app", "state"),
        ("cron", "state"),
        ("snap", "active_state"),
    ]
