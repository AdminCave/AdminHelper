# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module uptime-kuma (R-1243): the image louislam/uptime-kuma from Docker Hub or
ghcr.io gets the container check and GET /api/entry-page on 3001 in plain HTTP, never
/api/push/; anything but 200 is critical, and a server that waits for its database setup is a
warning; other images are not taken."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["uptime-kuma"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "louislam/uptime-kuma:2"
PORTS = ((3001, 3001),)


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


def _container(name, image=IMAGE, project="", service="", ports=PORTS, health="healthy"):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        # The image has a HEALTHCHECK of its own.
        "health": health,
        "ports": [{"private": p, "public": pub, "proto": "tcp"} for p, pub in ports],
        "mounts": [],
    }


# The compose file of the project: one service.
COMPOSE = [_container("kuma-uptime-kuma-1", project="kuma", service="uptime-kuma")]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "uptime-kuma"
    }


def _bind(block, key):
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _status(check_key, values, status="ok", error=""):
    block = _block(COMPOSE)
    config, why = probe_config(
        MODULE, CHECKS[check_key], "kuma", _found(block)["kuma"], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "entry"]
    assert MODULE.detect.container_images == [
        "louislam/uptime-kuma",
        "ghcr.io/louislam/uptime-kuma",
    ]
    assert MODULE.detect.units == []
    assert all(c.credential is None for c in MODULE.checks)


def test_the_entry_check_asks_the_entry_page_on_3001_in_plain_http():
    check = CHECKS["entry"]
    assert check.sensor == "http"
    assert check.params == {"path": "/api/entry-page", "method": "GET"}
    assert (check.target.kind, check.target.port_hint, check.target.scheme) == (
        "container",
        3001,
        "http",
    )
    assert check.fields == ["status_code", "data.type"]
    assert (check.interval, check.test_object) == (300, False)


def test_no_check_asks_the_push_route():
    # /api/push/<token> records a heartbeat of a push monitor.
    paths = [c.params.get("path", "") for c in MODULE.checks if c.sensor == "http"]
    assert paths == ["/api/entry-page"]
    assert not any("/api/push" in p for p in paths)


def test_uptime_kuma_in_its_project_gets_its_container_and_3001():
    block = _block(COMPOSE)
    assert _found(block) == {"kuma": {"services": {"uptime-kuma": "louislam/uptime-kuma"}}}
    assert _bind(block, "kuma") == {
        "container": ("kuma-uptime-kuma-1", None),
        "entry": ("kuma-uptime-kuma-1", None),
    }
    config, why = probe_config(
        MODULE, CHECKS["entry"], "kuma", _found(block)["kuma"], block["containers"]
    )
    assert why is None
    assert config["target"] == {
        "kind": "container",
        "name": "kuma-uptime-kuma-1",
        "port_hint": 3001,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    "image",
    [
        "louislam/uptime-kuma:1",
        "louislam/uptime-kuma:1.23.16",
        "louislam/uptime-kuma:2-rootless",
        "docker.io/louislam/uptime-kuma:2.5.11",
        "ghcr.io/louislam/uptime-kuma:2",
        "ghcr.io/louislam/uptime-kuma@sha256:" + "d" * 64,
    ],
)
def test_either_version_and_either_registry_get_the_container_and_3001(image):
    bound = _bind(_block([_container("uptime-kuma", image)]), "uptime-kuma")
    assert bound == {"container": ("uptime-kuma", None), "entry": ("uptime-kuma", None)}


@pytest.mark.parametrize(
    "image",
    [
        "louislam/dockge:1",
        "louislam/uptime-kuma-fork:2",
        "ghcr.io/someone/uptime-kuma:2",
        "elestio/uptime-kuma:latest",
    ],
)
def test_other_images_are_not_taken_for_uptime_kuma(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"status_code": 200, "data.type": "entryPage"}, "ok", "", "ok"),
        ({"status_code": 200, "data.type": "statusPageMatchedDomain"}, "ok", "", "ok"),
        # Version 2 before the admin chose its database: it monitors nothing.
        ({"status_code": 200, "data.type": "setup-database"}, "ok", "", "warning"),
        ({"status_code": 500}, "ok", "", "critical"),
        ({"status_code": 404}, "ok", "", "critical"),
        # A body that is no JSON object.
        ({}, "error", "the answer is no JSON object", "critical"),
        ({}, "error", "connection refused", "critical"),
        ({}, "error", "timed out after 10s", "critical"),
    ],
)
def test_the_entry_check(values, status, error, want):
    assert _status("entry", values, status, error) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ({"state": "running", "health": "starting", "restarts": 0}, "ok"),
        # The image's own HEALTHCHECK: GET / on 3001 failed five times.
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ({"state": "exited", "health": "none", "restarts": 1}, "critical"),
    ],
)
def test_the_container_rules(values, want):
    assert _status("container", values) == want


def test_the_card_shows_the_container_and_the_entry_page():
    assert [(i.check_key, i.field, i.label) for i in MODULE.card] == [
        ("container", "state", "Container"),
        ("container", "health", "Container health"),
        ("entry", "status_code", "Web"),
        ("entry", "data.type", "Entry page"),
    ]
