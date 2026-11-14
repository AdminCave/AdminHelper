# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module moodle (R-1242): erseco's and Bitnami's images get the container
check, which reads state and the image's own health; a development base or another image
is no Moodle."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["moodle"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "erseco/alpine-moodle:v5.3.0"


def _block(containers=()):
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


def _container(name, image=IMAGE, project="", service="", health="healthy"):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": health,
        # Both images expose 8080.
        "ports": [{"private": 8080, "public": 80, "proto": "tcp"}],
        "mounts": [],
    }


# The compose file of erseco's README: Moodle with PostgreSQL and Redis.
COMPOSE = [
    _container("lms-moodle-1", project="lms", service="moodle"),
    _container("lms-postgres-1", "postgres:alpine", "lms", "postgres", "none"),
    _container("lms-redis-1", "redis:alpine", "lms", "redis", "none"),
]


def _found(block):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "moodle"}


def _status(values):
    block = _block(COMPOSE)
    config, why = probe_config(MODULE, CHECKS["container"], "lms", _found(block)["lms"], COMPOSE)
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_the_container_check_only():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container"]
    assert CHECKS["container"].sensor == "container"
    assert CHECKS["container"].fields == ["state", "health", "restarts"]
    assert CHECKS["container"].credential is None
    assert MODULE.detect.units == []
    assert MODULE.detect.markers == []


def test_the_image_in_a_compose_project_gets_the_container_check_on_moodle():
    found = _found(_block(COMPOSE))
    assert found == {
        "lms": {
            "services": {
                "moodle": "erseco/alpine-moodle",
                "postgres": "postgres",
                "redis": "redis",
            },
            "containers": {
                "moodle": "lms-moodle-1",
                "postgres": "lms-postgres-1",
                "redis": "lms-redis-1",
            },
        }
    }
    config, why = probe_config(MODULE, CHECKS["container"], "lms", found["lms"], COMPOSE)
    assert why is None, why
    assert config["target"]["name"] == "lms-moodle-1"


@pytest.mark.parametrize(
    "image",
    [
        "erseco/alpine-moodle:latest",
        "ghcr.io/erseco/alpine-moodle:v5.2.1-php84",
        "bitnami/moodle:5.0",
        "docker.io/bitnami/moodle:4.5",
        "bitnamilegacy/moodle:4.5.2-debian-12-r0",
    ],
)
def test_each_image_started_without_compose_gets_the_container_check(image):
    block = _block([_container("moodle", image, health="none")])
    found = _found(block)
    assert list(found) == ["moodle"]
    config, why = probe_config(MODULE, CHECKS["container"], "moodle", found["moodle"], [])
    assert why is None, why
    assert config["target"]["name"] == "moodle"


@pytest.mark.parametrize(
    "image",
    [
        # Moodle's own image is a development base without Moodle in it.
        "moodlehq/moodle-php-apache:8.3",
        "erseco/alpine-php-webserver:3.24-php84",
        "ghcr.io/someone/alpine-moodle:1",
        "bitnami/mariadb:11.4",
    ],
)
def test_other_images_are_not_taken_for_moodle(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ({"state": "running", "health": "starting", "restarts": 0}, "ok"),
        # Bitnami's image has no health check.
        ({"state": "running", "health": "none", "restarts": 0}, "ok"),
        # /fpm-ping does not answer: PHP-FPM is stuck.
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ({"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ({"state": "restarting", "health": "none", "restarts": 4}, "critical"),
    ],
)
def test_the_container_rules(values, want):
    assert _status(values) == want


def test_the_card_shows_state_and_health():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("container", "health"),
    ]
