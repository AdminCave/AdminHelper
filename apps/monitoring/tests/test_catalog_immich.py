# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module immich (R-1241): the compose project is found by either of its own
images, each check binds to its service's container, and the ping is critical on any
answer but 200 with "pong"."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["immich"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
SERVER = "ghcr.io/immich-app/immich-server:v2"
ML = "ghcr.io/immich-app/immich-machine-learning:v2"


def _container(name, image, service, ports=(), project="photos"):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": "healthy",
        "ports": [{"private": p, "public": None, "proto": "tcp"} for p in ports],
        "mounts": [],
    }


COMPOSE = [
    _container("immich_server", SERVER, "immich-server", ports=[2283]),
    _container("immich_machine_learning", ML, "immich-machine-learning", ports=[3003]),
    _container("immich_redis", "docker.io/valkey/valkey:8-bookworm", "redis", ports=[6379]),
    _container("immich_postgres", "ghcr.io/immich-app/postgres:14", "database", ports=[5432]),
]


def _found(containers):
    inv = {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": [],
        "sockets": [],
        "containers": containers,
        "markers": {},
        "ports": [],
    }
    return {k: s for (m, k), s in match_inventory(inv, CATALOG).items() if m == "immich"}


def _config(check_key):
    config, why = probe_config(
        MODULE, CHECKS[check_key], "photos", _found(COMPOSE)["photos"], COMPOSE
    )
    assert why is None, why
    return config


def _status(check_key, **values):
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**_config(check_key), "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_a_container_check_per_service_and_the_ping():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["server", "machine_learning", "redis", "database", "ping"]
    assert CHECKS["ping"].params == {"path": "/api/server/ping", "method": "GET"}
    assert not any(c.test_object or c.credential for c in MODULE.checks)


def test_each_check_binds_to_its_service_container():
    assert {key: _config(key)["target"]["name"] for key in CHECKS} == {
        "server": "immich_server",
        "machine_learning": "immich_machine_learning",
        "redis": "immich_redis",
        "database": "immich_postgres",
        "ping": "immich_server",
    }
    assert _config("ping")["target"]["port_hint"] == 2283


@pytest.mark.parametrize("image", [SERVER, ML])
def test_either_own_image_finds_the_project(image):
    assert list(_found([_container("one", image, "x")])) == ["photos"]


def test_the_database_and_redis_images_alone_are_no_immich():
    assert _found(COMPOSE[2:]) == {}


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"status_code": 200, "data.res": "pong"}, "ok"),
        ({"status_code": 200, "data.res": "pang"}, "critical"),
        ({"status_code": 502}, "critical"),
        # A 200 without the answer (another app on the port) cannot be rated as up.
        ({"status_code": 200}, "unknown"),
    ],
)
def test_the_ping_rules(values, want):
    assert _status("ping", **values) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "healthy"}, "ok"),
        ({"state": "running", "health": "unhealthy"}, "critical"),
        ({"state": "exited", "health": "none"}, "critical"),
    ],
)
def test_the_container_rules(values, want):
    assert _status("machine_learning", **values) == want


def test_the_card_shows_the_containers():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("server", "state"),
        ("server", "restarts"),
        ("machine_learning", "state"),
        ("database", "state"),
        ("redis", "state"),
    ]
