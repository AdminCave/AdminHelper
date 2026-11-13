# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module onlyoffice (R-1242): the three images get the container check, whose
own health check (from 10.0) asks /healthcheck, and GET /healthcheck on the docservice's 8000
once the scan saw it listening in the container (R-1393); the package's ds-docservice.service
gets the unit check and GET /healthcheck on 8000; both health checks are test objects every
15 min; the converter, the split images and Nextcloud AIO's container are not ONLYOFFICE
Docs."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["onlyoffice"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "onlyoffice/documentserver:9.1.0"
UNIT = "ds-docservice.service"


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


def _container(
    name, image=IMAGE, project="", service="", ports=((80, "tcp"), (443, "tcp")), listening=None
):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        # The 9.x images have no HEALTHCHECK.
        "health": "none",
        "ports": [{"private": p, "public": p, "proto": proto} for p, proto in ports],
        "mounts": [],
        "listening": listening,
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


# The compose file of Docker-DocumentServer: one container, nginx's 80 and 443 published.
COMPOSE = [
    _container(
        "onlyoffice-documentserver", project="onlyoffice", service="onlyoffice-documentserver"
    )
]
# The package with the services it depends on.
PACKAGE = [
    _unit(UNIT),
    _unit("ds-converter.service"),
    _unit("ds-metrics.service"),
    _unit("nginx.service"),
    _unit("postgresql.service"),
    _unit("rabbitmq-server.service"),
    _unit("redis-server.service"),
]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "onlyoffice"
    }


def _bind(block, key):
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _status(check_key, values, status="ok", error=""):
    if check_key == "container":
        block, key = _block(COMPOSE), "onlyoffice"
    else:
        block, key = _block(units=PACKAGE), "onlyoffice"
    config, why = probe_config(
        MODULE, CHECKS[check_key], key, _found(block)[key], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_container_service_and_both_healthchecks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "service", "healthcheck", "container_healthcheck"]
    assert MODULE.detect.units == [UNIT]
    assert all(c.credential is None for c in MODULE.checks)


@pytest.mark.parametrize("key", ["healthcheck", "container_healthcheck"])
def test_the_healthcheck_is_a_get_and_a_test_object_every_15_min(key):
    # It writes and deletes a small object in the file storage on every call.
    check = CHECKS[key]
    assert check.params == {"path": "/healthcheck", "method": "GET"}
    assert check.fields == ["status_code"]
    assert (check.interval, check.test_object) == (900, True)
    assert check.rules == CHECKS["healthcheck"].rules


def test_the_container_is_asked_on_the_docservice_port_only():
    # The image exposes only nginx's 80 and 443; port 80 redirects to HTTPS once a
    # certificate is set up, so only the docservice's 8000 inside the container is asked.
    assert [
        (c.key, c.target.port_hint, c.target.scheme)
        for c in MODULE.checks
        if c.target.kind == "container"
    ] == [("container", None, None), ("container_healthcheck", 8000, "http")]


def test_the_project_without_listening_ports_gets_its_container_check_only():
    # An older agent tells no listening ports; 8000 is not exposed.
    block = _block(COMPOSE)
    assert _found(block) == {
        "onlyoffice": {"services": {"onlyoffice-documentserver": "onlyoffice/documentserver"}}
    }
    assert _bind(block, "onlyoffice") == {
        "container": ("onlyoffice-documentserver", None),
        "service": (None, "no unit for this instance"),
        "healthcheck": (None, "no unit for this instance"),
        "container_healthcheck": (None, "container onlyoffice-documentserver has no port 8000"),
    }


def test_the_docservice_listening_in_the_container_gets_the_healthcheck():
    container = _container(
        "onlyoffice-documentserver",
        project="onlyoffice",
        service="onlyoffice-documentserver",
        listening=[80, 443, 8000],
    )
    block = _block([container])
    assert _bind(block, "onlyoffice")["container_healthcheck"] == (
        "onlyoffice-documentserver",
        None,
    )
    config, _ = probe_config(
        MODULE,
        CHECKS["container_healthcheck"],
        "onlyoffice",
        _found(block)["onlyoffice"],
        block["containers"],
    )
    assert config["target"] == {
        "kind": "container",
        "name": "onlyoffice-documentserver",
        "port_hint": 8000,
        "scheme": "http",
    }
    assert config["test_object"] is True


def test_a_docservice_on_the_container_loopback_only_gets_no_healthcheck():
    # The scan leaves loopback out: 8000 there cannot be reached from the host.
    block = _block([_container("office", listening=[80, 443])])
    assert _bind(block, "office")["container_healthcheck"] == (
        None,
        "container office has no port 8000",
    )


@pytest.mark.parametrize(
    "image",
    [
        "onlyoffice/documentserver:10.0.0.1",
        "onlyoffice/documentserver-de:9.1.0",
        "onlyoffice/documentserver-ee:10.0.0.1",
        "docker.io/onlyoffice/documentserver:latest",
        "onlyoffice/documentserver@sha256:" + "c" * 64,
    ],
)
def test_each_image_started_without_compose_gets_its_container_check(image):
    block = _block([_container("office", image, listening=[80, 443, 8000])])
    assert _bind(block, "office") == {
        "container": ("office", None),
        "service": (None, "no unit for this instance"),
        "healthcheck": (None, "no unit for this instance"),
        "container_healthcheck": ("office", None),
    }


def test_the_package_gets_its_unit_and_the_healthcheck_on_8000():
    block = _block(units=PACKAGE)
    assert _found(block) == {"onlyoffice": {"matched_by": [f"unit:{UNIT}"]}}
    assert _bind(block, "onlyoffice") == {
        "container": (None, "no container for this instance"),
        "service": (UNIT, None),
        "healthcheck": (UNIT, None),
        "container_healthcheck": (None, "no container for this instance"),
    }
    config, _ = probe_config(
        MODULE, CHECKS["healthcheck"], "onlyoffice", _found(block)["onlyoffice"], []
    )
    assert config["target"] == {"kind": "unit", "name": UNIT, "port_hint": 8000, "scheme": "http"}
    assert config["test_object"] is True


def test_the_converter_alone_is_not_onlyoffice():
    assert _found(_block(units=[_unit("ds-converter.service"), _unit("ds-metrics.service")])) == {}


@pytest.mark.parametrize(
    "image",
    [
        "onlyoffice/documentserver-ie:7.2",
        "onlyoffice/docs-docservice:9.1.0",
        "onlyoffice/docs-converter:9.1.0",
        "nextcloud/aio-onlyoffice:latest",
        "ghcr.io/someone/documentserver:1",
    ],
)
def test_other_images_are_not_taken_for_onlyoffice(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        # 200 carries true or false; the agent reads no body that is no JSON object.
        ({"status_code": 200}, "ok", "", "ok"),
        ({"status_code": 404}, "ok", "", "critical"),
        ({"status_code": 500}, "ok", "", "critical"),
        # The docservice refuses or hangs: the probe fails.
        ({}, "error", "connection refused", "critical"),
        ({}, "error", "timeout", "critical"),
    ],
)
def test_the_healthcheck_is_critical_on_anything_but_200(values, status, error, want):
    assert _status("healthcheck", values, status, error) == want


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("container", {"state": "running", "health": "none", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        # From 10.0: /healthcheck answered false five times in a row.
        ("container", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ("container", {"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ("service", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_the_container_or_the_docservice_and_its_healthcheck():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("container", "health"),
        ("service", "active_state"),
        ("healthcheck", "status_code"),
        ("container_healthcheck", "status_code"),
    ]
