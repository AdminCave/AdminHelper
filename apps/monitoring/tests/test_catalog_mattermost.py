# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module mattermost (R-1242): both images get the container check, whose own
health check asks the server; the package's mattermost.service gets the unit check and the
system ping on 8065, never the deep ping with get_server_status."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["mattermost"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "mattermost/mattermost-enterprise-edition:release-11.1"
UNIT = "mattermost.service"


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


def _container(name, image=IMAGE, project="", service="", health="healthy"):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": health,
        "ports": [{"private": 8065, "public": 8065, "proto": "tcp"}],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


COMPOSE = [
    _container("mattermost-mattermost-1", project="mattermost", service="mattermost"),
    _container("mattermost-postgres-1", "postgres:17-alpine", "mattermost", "postgres", "none"),
]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "mattermost"
    }


def _bind(block, key):
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _status(check_key, values):
    if check_key == "container":
        block, key = _block(COMPOSE), "mattermost"
    else:
        block, key = _block(units=[_unit(UNIT)]), "mattermost"
    config, why = probe_config(
        MODULE, CHECKS[check_key], key, _found(block)[key], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_container_service_and_ping():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "service", "ping"]
    assert MODULE.detect.units == [UNIT]
    assert all(c.credential is None for c in MODULE.checks)


def test_the_ping_is_the_plain_one():
    # get_server_status=true writes and deletes a row in the database and tests the file store.
    assert CHECKS["ping"].params == {"path": "/api/v4/system/ping", "method": "GET"}
    assert CHECKS["ping"].fields == ["status_code"]
    assert (CHECKS["ping"].interval, CHECKS["ping"].test_object) == (300, False)


def test_the_image_in_a_compose_project_gets_its_container_check_only():
    block = _block(COMPOSE)
    assert _found(block) == {
        "mattermost": {
            "services": {
                "mattermost": "mattermost/mattermost-enterprise-edition",
                "postgres": "postgres",
            }
        }
    }
    assert _bind(block, "mattermost") == {
        "container": ("mattermost-mattermost-1", None),
        "service": (None, "no unit for this instance"),
        "ping": (None, "no unit for this instance"),
    }


@pytest.mark.parametrize(
    "image",
    [
        "mattermost/mattermost-team-edition:11.1.0",
        "docker.io/mattermost/mattermost-enterprise-edition:release-11.1",
        "mattermost/mattermost-enterprise-edition@sha256:" + "a" * 64,
    ],
)
def test_each_image_started_without_compose_gets_its_container_check(image):
    block = _block([_container("mattermost", image)])
    assert _bind(block, "mattermost")["container"] == ("mattermost", None)


def test_the_package_asks_the_ping_on_8065():
    block = _block(units=[_unit(UNIT), _unit("postgresql.service"), _unit("nginx.service")])
    assert _found(block) == {"mattermost": {"matched_by": [f"unit:{UNIT}"]}}
    assert _bind(block, "mattermost") == {
        "container": (None, "no container for this instance"),
        "service": (UNIT, None),
        "ping": (UNIT, None),
    }
    config, _ = probe_config(MODULE, CHECKS["ping"], "mattermost", _found(block)["mattermost"], [])
    assert config["target"] == {"kind": "unit", "name": UNIT, "port_hint": 8065, "scheme": "http"}


@pytest.mark.parametrize(
    "image",
    [
        "mattermost/mattermost-preview:latest",
        "mattermost/mattermost-push-proxy:6.4.0",
        "mattermost/rtcd:v1.1.0",
        "ghcr.io/someone/mattermost-team-edition:1",
    ],
)
def test_other_images_are_not_taken_for_mattermost(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize(
    ("code", "want"),
    [
        (200, "ok"),
        # status UNHEALTHY: the goroutines passed GoroutineHealthThreshold.
        (500, "critical"),
        (502, "critical"),
    ],
)
def test_the_ping_is_critical_on_anything_but_200(code, want):
    assert _status("ping", {"status_code": code}) == want


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("container", {"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "starting", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ("container", {"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ("service", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("service", {"active_state": "activating", "sub_state": "auto-restart"}, "critical"),
        ("service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_the_container_or_the_service_and_the_ping():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("container", "health"),
        ("service", "active_state"),
        ("ping", "status_code"),
    ]
