# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module synapse (R-1242): both images get the container check, whose own
health check asks /health; the package's matrix-synapse.service gets the unit check and
/health on 8008; workers of the image in one project bind no container check."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["synapse"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "matrixdotorg/synapse:v1.142.0"
UNIT = "matrix-synapse.service"


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
        # The image exposes 8008 and 8448.
        "ports": [{"private": 8008, "public": 8008, "proto": "tcp"}],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


COMPOSE = [
    _container("matrix-synapse-1", project="matrix", service="synapse"),
    _container("matrix-db-1", "postgres:17-alpine", "matrix", "db", "none"),
]


def _found(block):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "synapse"}


def _bind(block, key):
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _status(check_key, values):
    if check_key == "container":
        block, key = _block(COMPOSE), "matrix"
    else:
        block, key = _block(units=[_unit(UNIT)]), "synapse"
    config, why = probe_config(MODULE, CHECKS[check_key], key, _found(block)[key], COMPOSE)
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_container_service_and_health():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "service", "health"]
    assert MODULE.detect.units == [UNIT]
    assert CHECKS["health"].params == {"path": "/health", "method": "GET"}
    assert CHECKS["health"].fields == ["status_code"]
    assert (CHECKS["health"].interval, CHECKS["health"].test_object) == (300, False)
    assert all(c.credential is None for c in MODULE.checks)


def test_the_image_in_a_compose_project_gets_its_container_check_only():
    block = _block(COMPOSE)
    assert _found(block) == {
        "matrix": {"services": {"synapse": "matrixdotorg/synapse", "db": "postgres"}}
    }
    assert _bind(block, "matrix") == {
        "container": ("matrix-synapse-1", None),
        "service": (None, "no unit for this instance"),
        "health": (None, "no unit for this instance"),
    }


@pytest.mark.parametrize(
    "image",
    [
        "matrixdotorg/synapse:latest",
        "docker.io/matrixdotorg/synapse:v1.142.0",
        "ghcr.io/element-hq/synapse:v1.142.0",
    ],
)
def test_each_image_started_without_compose_gets_its_container_check(image):
    block = _block([_container("synapse", image)])
    assert _bind(block, "synapse")["container"] == ("synapse", None)


def test_workers_of_the_image_in_one_project_bind_no_container_check():
    block = _block(
        [
            _container("matrix-synapse-1", project="matrix", service="synapse"),
            _container("matrix-worker-1", project="matrix", service="worker"),
        ]
    )
    assert _bind(block, "matrix")["container"] == (
        None,
        "several containers for this instance: matrix-synapse-1, matrix-worker-1",
    )


def test_the_package_asks_health_on_8008():
    block = _block(units=[_unit(UNIT), _unit("postgresql.service"), _unit("nginx.service")])
    assert _found(block) == {"synapse": {"matched_by": [f"unit:{UNIT}"]}}
    assert _bind(block, "synapse") == {
        "container": (None, "no container for this instance"),
        "service": (UNIT, None),
        "health": (UNIT, None),
    }
    config, _ = probe_config(MODULE, CHECKS["health"], "synapse", _found(block)["synapse"], [])
    assert config["target"] == {"kind": "unit", "name": UNIT, "port_hint": 8008, "scheme": "http"}


@pytest.mark.parametrize(
    "image",
    ["matrixdotorg/sygnal:latest", "ghcr.io/element-hq/element-web:v1.12.0", "ghcr.io/x/synapse:1"],
)
def test_other_matrix_images_are_not_taken_for_synapse(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize(("code", "want"), [(200, "ok"), (502, "critical"), (404, "critical")])
def test_health_is_critical_on_anything_but_200(code, want):
    assert _status("health", {"status_code": code}) == want


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("container", {"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "starting", "restarts": 0}, "ok"),
        # /health does not answer within 5 s.
        ("container", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ("container", {"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ("service", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("service", {"active_state": "activating", "sub_state": "auto-restart"}, "critical"),
        ("service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_the_container_or_the_service_and_health():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("container", "health"),
        ("service", "active_state"),
        ("health", "status_code"),
    ]
