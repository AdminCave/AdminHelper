# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module vaultwarden (R-1241): each of the three images gets the container
check, whose own health check asks /alive; the systemd service gets the unit check and
/alive on Rocket's port 8000 in plain HTTP or TLS; /admin is never asked."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["vaultwarden"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "vaultwarden/server:1.35.2"
UNIT = "vaultwarden.service"


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


def _container(name, image=IMAGE, project="", service=""):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": "healthy",
        # The image exposes 80.
        "ports": [{"private": 80, "public": 8080, "proto": "tcp"}],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


COMPOSE = [_container("vw-vaultwarden-1", project="vw", service="vaultwarden")]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "vaultwarden"
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
        block, key = _block(COMPOSE), "vw"
    else:
        block, key = _block(units=[_unit(UNIT)]), "vaultwarden"
    config, why = probe_config(MODULE, CHECKS[check_key], key, _found(block)[key], COMPOSE)
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_container_service_and_alive():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "service", "alive"]
    assert CHECKS["alive"].params == {"path": "/alive", "method": "GET"}
    assert CHECKS["alive"].fields == ["status_code"]
    assert (CHECKS["alive"].interval, CHECKS["alive"].test_object) == (300, False)
    assert all(c.credential is None for c in MODULE.checks)


def test_the_image_in_a_compose_project_gets_its_container_check_only():
    assert _found(_block(COMPOSE)) == {
        "vw": {
            "services": {"vaultwarden": "vaultwarden/server"},
            "containers": {"vaultwarden": "vw-vaultwarden-1"},
        }
    }
    assert _bind(_block(COMPOSE), "vw") == {
        "container": ("vw-vaultwarden-1", None),
        "service": (None, "no unit for this instance"),
        "alive": (None, "no unit for this instance"),
    }


@pytest.mark.parametrize(
    "image",
    [
        "vaultwarden/server:1.35.2-alpine",
        "ghcr.io/dani-garcia/vaultwarden:1.35.2",
        "quay.io/vaultwarden/server:latest",
    ],
)
def test_each_image_started_without_compose_gets_its_container_check(image):
    block = _block([_container("vaultwarden", image)])
    assert _bind(block, "vaultwarden") == {
        "container": ("vaultwarden", None),
        "service": (None, "no unit for this instance"),
        "alive": (None, "no unit for this instance"),
    }


def test_the_systemd_service_asks_alive_on_rockets_port_8000():
    block = _block(units=[_unit(UNIT)])
    assert _found(block) == {"vaultwarden": {"matched_by": [f"unit:{UNIT}"]}}
    assert _bind(block, "vaultwarden") == {
        "container": (None, "no container for this instance"),
        "service": (UNIT, None),
        "alive": (UNIT, None),
    }
    config, _ = probe_config(
        MODULE, CHECKS["alive"], "vaultwarden", _found(block)["vaultwarden"], []
    )
    assert config["target"] == {"kind": "unit", "name": UNIT, "port_hint": 8000, "scheme": "auto"}


@pytest.mark.parametrize(
    "image", ["vaultwarden/web-vault:v2025.12.0", "ghcr.io/someone/vaultwarden:1"]
)
def test_the_web_vault_and_foreign_images_are_not_taken_for_vaultwarden(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize(
    ("code", "want"),
    [
        (200, "ok"),
        # The database does not answer.
        (503, "critical"),
        # A DOMAIN with a path moved /alive below it.
        (404, "critical"),
    ],
)
def test_alive_is_critical_on_anything_but_200(code, want):
    assert _status("alive", {"status_code": code}) == want


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("container", {"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "starting", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ("container", {"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ("service", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_the_container_or_the_service_and_alive():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("container", "health"),
        ("service", "active_state"),
        ("alive", "status_code"),
    ]
