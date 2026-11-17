# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module edulution (R-1489): the compose project of the installer is found by
the UI's or the API's image, each check binds to its service's container, and the API's
health route on 3000 is critical on anything but 200."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["edulution"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
UI = "ghcr.io/edulution-io/edulution-ui:latest"
API = "ghcr.io/edulution-io/edulution-api:latest"


def _container(name, image, service, ports=(), project="edulution-ui"):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": "healthy",
        "ports": [{"private": p, "public": pub, "proto": "tcp"} for p, pub in ports],
        "mounts": [],
    }


# The services and container names of the installer's template; only Traefik publishes.
COMPOSE = [
    _container("edulution-ui", UI, "edu-ui", [(80, None)]),
    _container("edulution-api", API, "edu-api", [(3000, None)]),
    _container("edulution-db", "mongo:7", "edu-db", [(27017, None)]),
    _container("edulution-redis", "redis:8.6", "edu-redis", [(6379, None)]),
    _container("edulution-traefik", "traefik:v3.1", "edu-traefik", [(80, 80), (443, 443)]),
    _container(
        "edulution-keycloak", "quay.io/keycloak/keycloak:26.7.3", "edu-keycloak", [(8080, None)]
    ),
    _container("edulution-keycloak-db", "postgres:16", "edu-keycloak-db", [(5432, None)]),
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
    return {k: s for (m, k), s in match_inventory(inv, CATALOG).items() if m == "edulution"}


def _config(check_key):
    config, why = probe_config(
        MODULE, CHECKS[check_key], "edulution-ui", _found(COMPOSE)["edulution-ui"], COMPOSE
    )
    assert why is None, why
    return config


def _status(check_key, values, status="ok", error=""):
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**_config(check_key), "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_a_container_check_per_service_and_the_health_route():
    assert CATALOG.errors == ()
    assert list(CHECKS) == [
        "ui",
        "api",
        "database",
        "redis",
        "traefik",
        "keycloak",
        "keycloak_database",
        "health",
    ]
    assert MODULE.detect.container_images == [
        "ghcr.io/edulution-io/edulution-ui",
        "ghcr.io/edulution-io/edulution-api",
    ]
    assert not any(c.test_object or c.credential for c in MODULE.checks)


def test_the_health_check_asks_the_api_on_3000_in_plain_http():
    check = CHECKS["health"]
    assert check.sensor == "http"
    # The request the template's own HEALTHCHECK sends, without a login.
    assert check.params == {"path": "/edu-api/health/check", "method": "GET"}
    assert (check.target.service, check.target.port_hint, check.target.scheme) == (
        "edu-api",
        3000,
        "http",
    )
    assert check.fields == ["status_code"]
    assert check.interval == 300


def test_each_check_binds_to_its_service_container():
    assert {key: _config(key)["target"]["name"] for key in CHECKS} == {
        "ui": "edulution-ui",
        "api": "edulution-api",
        "database": "edulution-db",
        "redis": "edulution-redis",
        "traefik": "edulution-traefik",
        "keycloak": "edulution-keycloak",
        "keycloak_database": "edulution-keycloak-db",
        "health": "edulution-api",
    }
    assert _config("health")["target"]["port_hint"] == 3000


@pytest.mark.parametrize(
    "image",
    [UI, API, "ghcr.io/edulution-io/edulution-api:2.4.0", "ghcr.io/edulution-io/edulution-ui"],
)
def test_either_own_image_finds_the_project(image):
    assert list(_found([_container("one", image, "x")])) == ["edulution-ui"]


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/edulution-io/edulution-installer:2.1.2",
        "ghcr.io/edulution-io/edulution-ui-fork:1",
        "ghcr.io/someone/edulution-ui:latest",
    ],
)
def test_other_images_are_no_edulution(image):
    assert _found([_container("one", image, "x")]) == {}


def test_the_shared_images_alone_are_no_edulution():
    assert _found(COMPOSE[2:]) == {}


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"status_code": 200}, "ok", "", "ok"),
        ({"status_code": 503}, "ok", "", "critical"),
        ({"status_code": 401}, "ok", "", "critical"),
        ({}, "error", "connection refused", "critical"),
    ],
)
def test_the_health_check_is_critical_on_anything_but_200(values, status, error, want):
    assert _status("health", values, status, error) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ({"state": "exited", "health": "none", "restarts": 1}, "critical"),
    ],
)
def test_the_container_rules(values, want):
    assert _status("api", values) == want


def test_the_card_shows_the_core_containers_and_the_health_route():
    assert [(i.check_key, i.field, i.label) for i in MODULE.card] == [
        ("ui", "state", "UI"),
        ("api", "state", "API"),
        ("health", "status_code", "API health"),
        ("database", "state", "MongoDB"),
        ("traefik", "state", "Traefik"),
        ("keycloak", "state", "Keycloak"),
    ]
