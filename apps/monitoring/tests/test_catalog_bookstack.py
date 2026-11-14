# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module bookstack (R-1243): the images of linuxserver.io and solidnerd get the
container check and GET /status in plain HTTP, as a test object every 15 minutes, on 80 for
linuxserver.io and on 8080 for solidnerd; the check whose port the container lacks is not
bound; anything but 200 is critical, a database, cache or session that failed (500) too; the
database container of the project and other images are not taken."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["bookstack"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
LSIO = "lscr.io/linuxserver/bookstack:25.07.20250804"
SOLIDNERD = "solidnerd/bookstack:25.7"
# linuxserver.io: EXPOSE 80 443, the documentation publishes 80 as 6875.
LSIO_PORTS = ((80, 6875), (443, None))
# solidnerd: EXPOSE 8080.
SOLIDNERD_PORTS = ((8080, 8080),)


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


def _container(name, image=LSIO, project="", service="", ports=LSIO_PORTS):
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


# BookStack with its database in one compose project, as linuxserver.io documents it.
COMPOSE = [
    _container("wiki-bookstack-1", project="wiki", service="bookstack"),
    _container(
        "wiki-db-1", "lscr.io/linuxserver/mariadb:11.4", "wiki", "bookstack_db", ((3306, None),)
    ),
]
SOLIDNERD_COMPOSE = [
    _container("docs-app-1", SOLIDNERD, "docs", "app", SOLIDNERD_PORTS),
    _container("docs-mysql-1", "mysql:8.4", "docs", "mysql", ((3306, None),)),
]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "bookstack"
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
    block, key = (
        (_block(SOLIDNERD_COMPOSE), "docs")
        if check_key == "status_8080"
        else (_block(COMPOSE), "wiki")
    )
    config, why = probe_config(
        MODULE, CHECKS[check_key], key, _found(block)[key], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "status", "status_8080"]
    assert MODULE.detect.container_images == [
        "lscr.io/linuxserver/bookstack",
        "ghcr.io/linuxserver/bookstack",
        "linuxserver/bookstack",
        "solidnerd/bookstack",
    ]
    assert MODULE.detect.units == []
    assert all(c.credential is None for c in MODULE.checks)


@pytest.mark.parametrize(("key", "port"), [("status", 80), ("status_8080", 8080)])
def test_both_status_checks_are_test_objects_every_15_minutes(key, port):
    check = CHECKS[key]
    assert check.sensor == "http"
    assert check.params == {"path": "/status", "method": "GET"}
    assert (check.target.kind, check.target.port_hint, check.target.scheme) == (
        "container",
        port,
        "http",
    )
    assert check.fields == ["status_code"]
    # Each call without a cookie leaves a session behind.
    assert (check.interval, check.test_object) == (900, True)


def test_linuxserver_in_its_project_gets_its_container_and_80_only():
    block = _block(COMPOSE)
    assert _found(block) == {
        "wiki": {
            "services": {
                "bookstack": "lscr.io/linuxserver/bookstack",
                "bookstack_db": "lscr.io/linuxserver/mariadb",
            },
            "containers": {"bookstack": "wiki-bookstack-1", "bookstack_db": "wiki-db-1"},
        }
    }
    assert _bind(block, "wiki") == {
        "container": ("wiki-bookstack-1", None),
        "status": ("wiki-bookstack-1", None),
        "status_8080": (None, "container wiki-bookstack-1 has no port 8080"),
    }
    assert _target("status", block, "wiki") == {
        "kind": "container",
        "name": "wiki-bookstack-1",
        "port_hint": 80,
        "scheme": "http",
    }


def test_solidnerd_in_its_project_gets_its_container_and_8080_only():
    block = _block(SOLIDNERD_COMPOSE)
    assert _bind(block, "docs") == {
        "container": ("docs-app-1", None),
        "status": (None, "container docs-app-1 has no port 80"),
        "status_8080": ("docs-app-1", None),
    }
    assert _target("status_8080", block, "docs") == {
        "kind": "container",
        "name": "docs-app-1",
        "port_hint": 8080,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    ("image", "ports", "status", "status_8080"),
    [
        ("lscr.io/linuxserver/bookstack:latest", LSIO_PORTS, True, False),
        ("ghcr.io/linuxserver/bookstack:version-v25.07", LSIO_PORTS, True, False),
        ("linuxserver/bookstack:25.07.20250804", LSIO_PORTS, True, False),
        ("docker.io/linuxserver/bookstack", LSIO_PORTS, True, False),
        ("solidnerd/bookstack:latest", SOLIDNERD_PORTS, False, True),
        ("docker.io/solidnerd/bookstack:25.7", SOLIDNERD_PORTS, False, True),
        # Stopped or on the host's network: the scan saw no ports, both bind.
        (LSIO, (), True, True),
    ],
)
def test_the_image_started_without_compose_binds_the_check_of_its_port(
    image, ports, status, status_8080
):
    bound = _bind(_block([_container("bookstack", image, ports=ports)]), "bookstack")
    assert bound["container"] == ("bookstack", None)
    assert (bound["status"][0] is not None, bound["status_8080"][0] is not None) == (
        status,
        status_8080,
    )


@pytest.mark.parametrize(
    "image",
    [
        "bookstackapp/bookstack:latest",
        "ghcr.io/someone/bookstack:1",
        "lscr.io/linuxserver/mariadb:11.4",
        "solidnerd/bookstack-backup:1",
    ],
)
def test_other_images_are_not_taken_for_bookstack(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize("check_key", ["status", "status_8080"])
@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"status_code": 200}, "ok", "", "ok"),
        # The database, the cache or the session failed.
        ({"status_code": 500}, "ok", "", "critical"),
        ({"status_code": 404}, "ok", "", "critical"),
        ({}, "error", "connection refused", "critical"),
        ({}, "error", "timed out after 10s", "critical"),
        # On the host's network the check of the other image finds two ports.
        ({}, "ambiguous_target", "container bookstack listens on ports 80, 443", "unknown"),
    ],
)
def test_the_status_check_is_critical_on_anything_but_200(check_key, values, status, error, want):
    assert _status(check_key, values, status, error) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "none", "restarts": 0}, "ok"),
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        # A HEALTHCHECK the compose file adds.
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ({"state": "exited", "health": "none", "restarts": 1}, "critical"),
    ],
)
def test_the_container_rules(values, want):
    assert _status("container", values) == want


def test_the_card_shows_the_container_and_the_status_of_either_port():
    assert [(i.check_key, i.field, i.label) for i in MODULE.card] == [
        ("container", "state", "Container"),
        ("container", "health", "Container health"),
        ("status", "status_code", "Status"),
        ("status_8080", "status_code", "Status"),
    ]
