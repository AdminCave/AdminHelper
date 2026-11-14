# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module odoo (R-1243): the official image gets the container check and GET
/web/health?db_server_status=1 on 8069 in plain HTTP; the package's odoo.service gets the
unit check and the same; anything but 200 is critical, a refused database server (500) and
an Odoo before 15 (404) too; the database container of the project, units under other names
and other images are not taken."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["odoo"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "odoo:18.0"
UNIT = "odoo.service"
# 8069 published, the other two only exposed (EXPOSE 8069 8071 8072).
PORTS = ((8069, 8069), (8071, None), (8072, None))


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
        # The image has no HEALTHCHECK of its own.
        "health": "none",
        "ports": [{"private": p, "public": pub, "proto": "tcp"} for p, pub in ports],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


# Odoo with its database in one compose project.
COMPOSE = [
    _container("erp-odoo-1", project="erp", service="odoo"),
    _container("erp-db-1", "postgres:17", "erp", "db", ((5432, None),)),
]


def _found(block):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "odoo"}


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
        block, key = _block(COMPOSE), "erp"
    else:
        block, key = _block(units=[_unit(UNIT)]), "odoo"
    config, why = probe_config(
        MODULE, CHECKS[check_key], key, _found(block)[key], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "health", "service", "service_health"]
    assert MODULE.detect.container_images == ["odoo"]
    assert MODULE.detect.units == [UNIT]
    assert all(c.credential is None for c in MODULE.checks)


def test_both_health_checks_ask_the_database_server_too_on_8069_in_plain_http():
    for key in ("health", "service_health"):
        check = CHECKS[key]
        assert check.sensor == "http"
        assert check.params == {"path": "/web/health?db_server_status=1", "method": "GET"}
        assert (check.target.port_hint, check.target.scheme) == (8069, "http")
        assert check.fields == ["status_code"]
        assert (check.interval, check.test_object) == (300, False)


def test_odoo_in_its_project_gets_its_container_and_8069():
    block = _block(COMPOSE)
    assert _found(block) == {
        "erp": {
            "services": {"db": "postgres", "odoo": "odoo"},
            "containers": {"db": "erp-db-1", "odoo": "erp-odoo-1"},
        }
    }
    assert _bind(block, "erp") == {
        "container": ("erp-odoo-1", None),
        "health": ("erp-odoo-1", None),
        "service": (None, "no unit for this instance"),
        "service_health": (None, "no unit for this instance"),
    }
    assert _target("health", block, "erp") == {
        "kind": "container",
        "name": "erp-odoo-1",
        "port_hint": 8069,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    "image",
    [
        "odoo:17",
        "odoo:latest",
        "docker.io/library/odoo:19.0",
        "odoo@sha256:" + "c" * 64,
    ],
)
def test_the_image_started_without_compose_gets_the_container_and_8069(image):
    block = _block([_container("odoo", image)])
    bound = _bind(block, "odoo")
    assert (bound["container"], bound["health"]) == (("odoo", None), ("odoo", None))


def test_the_package_gets_its_unit_and_8069():
    block = _block(units=[_unit(UNIT), _unit("postgresql.service"), _unit("nginx.service")])
    assert _found(block) == {"odoo": {"matched_by": [f"unit:{UNIT}"]}}
    assert _bind(block, "odoo") == {
        "container": (None, "no container for this instance"),
        "health": (None, "no container for this instance"),
        "service": (UNIT, None),
        "service_health": (UNIT, None),
    }
    assert _target("service_health", block, "odoo") == {
        "kind": "unit",
        "name": UNIT,
        "port_hint": 8069,
        "scheme": "http",
    }


def test_a_unit_under_another_name_is_not_taken():
    assert _found(_block(units=[_unit("odoo18.service"), _unit("odoo-server.service")])) == {}


@pytest.mark.parametrize(
    "image",
    [
        "bitnami/odoo:18",
        "odoo/odoo:18.0",
        "ghcr.io/someone/odoo:18",
        "odoo-enterprise:18",
    ],
)
def test_other_images_are_not_taken_for_odoo(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize("check_key", ["health", "service_health"])
@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"status_code": 200}, "ok", "", "ok"),
        # From 16 on: the database server refused the cursor.
        ({"status_code": 500}, "ok", "", "critical"),
        # An Odoo before 15 has no /web/health.
        ({"status_code": 404}, "ok", "", "critical"),
        ({}, "error", "connection refused", "critical"),
        ({}, "error", "timed out after 10s", "critical"),
    ],
)
def test_the_health_check_is_critical_on_anything_but_200(check_key, values, status, error, want):
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
        ("service", {"active_state": "activating", "sub_state": "auto-restart"}, "critical"),
        ("service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_the_container_or_the_service_and_the_health():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("container", "health"),
        ("health", "status_code"),
        ("service", "active_state"),
        ("service_health", "status_code"),
    ]
