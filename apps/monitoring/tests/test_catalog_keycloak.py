# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module keycloak (R-1242): the image from quay.io or Docker Hub gets the
container check and GET /health/ready on the management port 9000 in plain HTTP; a
keycloak.service gets the unit check and the same; anything but 200 is critical, a Keycloak
without health-enabled too; an image before 25.0 has no 9000 and gets no readiness check;
the operator image and the discontinued images are not Keycloak."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["keycloak"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "quay.io/keycloak/keycloak:26.4.2"
UNIT = "keycloak.service"
# 8080 published, the management port only exposed (EXPOSE 8080 8443 9000 from 25.0 on).
PORTS = ((8080, 8080), (8443, None), (9000, None))


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


def _container(name, image=IMAGE, project="", service="", ports=PORTS):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        # The images have no HEALTHCHECK of their own.
        "health": "none",
        "ports": [{"private": p, "public": pub, "proto": "tcp"} for p, pub in ports],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


# Keycloak with its database in one compose project.
COMPOSE = [
    _container("sso-keycloak-1", project="sso", service="keycloak"),
    _container("sso-db-1", "postgres:17", "sso", "db", ((5432, None),)),
]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "keycloak"
    }


def _bind(block, key):
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _target(check_key, block, key):
    config, why = probe_config(
        MODULE, CHECKS[check_key], key, _found(block)[key], block["containers"]
    )
    assert why is None, why
    return config["target"]


def _status(check_key, values, status="ok", error=""):
    if CHECKS[check_key].target.kind == "container":
        block, key = _block(COMPOSE), "sso"
    else:
        block, key = _block(units=[_unit(UNIT)]), "keycloak"
    config, why = probe_config(
        MODULE, CHECKS[check_key], key, _found(block)[key], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "ready", "service", "service_ready"]
    assert MODULE.detect.container_images == ["quay.io/keycloak/keycloak", "keycloak/keycloak"]
    assert MODULE.detect.units == [UNIT]
    assert all(c.credential is None for c in MODULE.checks)


def test_both_readiness_checks_get_health_ready_on_9000_in_plain_http():
    for key in ("ready", "service_ready"):
        check = CHECKS[key]
        assert check.sensor == "http"
        assert check.params == {"path": "/health/ready", "method": "GET"}
        assert (check.target.port_hint, check.target.scheme) == (9000, "http")
        assert check.fields == ["status_code"]
        assert (check.interval, check.test_object) == (300, False)


def test_keycloak_in_its_project_gets_its_container_and_9000():
    block = _block(COMPOSE)
    assert _found(block) == {
        "sso": {"services": {"db": "postgres", "keycloak": "quay.io/keycloak/keycloak"}}
    }
    assert _bind(block, "sso") == {
        "container": ("sso-keycloak-1", None),
        "ready": ("sso-keycloak-1", None),
        "service": (None, "no unit for this instance"),
        "service_ready": (None, "no unit for this instance"),
    }
    assert _target("ready", block, "sso") == {
        "kind": "container",
        "name": "sso-keycloak-1",
        "port_hint": 9000,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    "image",
    [
        "quay.io/keycloak/keycloak:25.0.0",
        "quay.io/keycloak/keycloak@sha256:" + "e" * 64,
        "keycloak/keycloak:26.4",
        "docker.io/keycloak/keycloak:latest",
    ],
)
def test_the_image_started_without_compose_gets_the_container_and_9000(image):
    block = _block([_container("keycloak", image)])
    bound = _bind(block, "keycloak")
    assert (bound["container"], bound["ready"]) == (("keycloak", None), ("keycloak", None))


def test_an_image_before_25_has_no_management_port_and_no_readiness_check():
    block = _block([_container("keycloak", "quay.io/keycloak/keycloak:24.0.5", ports=PORTS[:2])])
    bound = _bind(block, "keycloak")
    assert bound["container"] == ("keycloak", None)
    assert bound["ready"] == (None, "container keycloak has no port 9000")


def test_a_keycloak_unit_gets_the_unit_check_and_9000():
    block = _block(units=[_unit(UNIT), _unit("postgresql.service"), _unit("nginx.service")])
    assert _found(block) == {"keycloak": {"matched_by": [f"unit:{UNIT}"]}}
    assert _bind(block, "keycloak") == {
        "container": (None, "no container for this instance"),
        "ready": (None, "no container for this instance"),
        "service": (UNIT, None),
        "service_ready": (UNIT, None),
    }
    assert _target("service_ready", block, "keycloak") == {
        "kind": "unit",
        "name": UNIT,
        "port_hint": 9000,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    "image",
    [
        "quay.io/keycloak/keycloak-operator:26.4.2",
        "keycloak/keycloak-gatekeeper:10.0.0",
        "bitnami/keycloak:26.3",
        "jboss/keycloak:16.1.1",
        "ghcr.io/someone/keycloak:1",
    ],
)
def test_other_images_are_not_taken_for_keycloak(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize("check_key", ["ready", "service_ready"])
@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"status_code": 200}, "ok", "", "ok"),
        # A check failed: DOWN.
        ({"status_code": 503}, "ok", "", "critical"),
        # health-enabled off and metrics on: the management port answers, without health.
        ({"status_code": 404}, "ok", "", "critical"),
        # health-enabled off: the management port is closed, or another port answers.
        ({}, "error", "connection refused", "critical"),
        ({}, "error", "timeout", "critical"),
    ],
)
def test_the_readiness_check_is_critical_on_anything_but_200(
    check_key, values, status, error, want
):
    assert _status(check_key, values, status, error) == want


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("container", {"state": "running", "health": "none", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        # A HEALTHCHECK the compose file adds.
        ("container", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ("container", {"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ("service", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_the_container_or_the_service_and_the_readiness():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("container", "health"),
        ("ready", "status_code"),
        ("service", "active_state"),
        ("service_ready", "status_code"),
    ]
