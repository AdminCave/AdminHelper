# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module bitwarden (R-1241): the standard install's nginx, api, identity and
mssql containers get their checks, whose health carries each image's own health check;
Bitwarden Lite gets the check of its one container; nothing is asked over HTTP."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["bitwarden"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
VERSION = "2026.10.1"


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


def _container(name, image, project="", service="", ports=()):
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


def _standard(*services):
    # bitwarden.sh runs the compose file in bwdata/docker: project "docker", fixed names.
    return [
        _container(
            "bitwarden-" + s,
            f"ghcr.io/bitwarden/{s}:{VERSION}",
            "docker",
            s,
            ports=[8080, 8443] if s == "nginx" else [5000],
        )
        for s in services
    ]


STANDARD = _standard(
    "mssql",
    "web",
    "attachments",
    "api",
    "identity",
    "sso",
    "admin",
    "icons",
    "notifications",
    "events",
    "nginx",
)
LITE = [
    _container(
        "bitwarden-bitwarden-1",
        f"ghcr.io/bitwarden/lite:{VERSION}",
        "bitwarden",
        "bitwarden",
        ports=[8080, 8443],
    ),
    _container("bitwarden-db-1", "mariadb:10", "bitwarden", "db", ports=[3306]),
]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "bitwarden"
    }


def _bind(block, key):
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _status(check_key, values):
    block, key = (
        (_block(LITE), "bitwarden") if check_key == "lite" else (_block(STANDARD), "docker")
    )
    config, why = probe_config(
        MODULE, CHECKS[check_key], key, _found(block)[key], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_container_checks_only():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["nginx", "api", "identity", "mssql", "lite"]
    assert {c.sensor for c in MODULE.checks} == {"container"}
    assert [c.target.service for c in MODULE.checks] == ["nginx", "api", "identity", "mssql", ""]


def test_the_standard_install_binds_each_service_and_leaves_the_lite_check_unbound():
    names = sorted(c["name"] for c in STANDARD)
    assert _bind(_block(STANDARD), "docker") == {
        "nginx": ("bitwarden-nginx", None),
        "api": ("bitwarden-api", None),
        "identity": ("bitwarden-identity", None),
        "mssql": ("bitwarden-mssql", None),
        "lite": (None, "several containers for this instance: " + ", ".join(names)),
    }


def test_an_external_database_leaves_the_mssql_check_unbound():
    block = _block(_standard("web", "api", "identity", "admin", "nginx"))
    bound = _bind(block, "docker")
    assert bound["mssql"] == (None, "no container for this instance")
    assert bound["api"] == ("bitwarden-api", None)


def test_lite_in_its_compose_project_gets_the_check_of_its_one_container():
    assert _found(_block(LITE)) == {
        "bitwarden": {"services": {"bitwarden": "ghcr.io/bitwarden/lite", "db": "mariadb"}}
    }
    assert _bind(_block(LITE), "bitwarden") == {
        "nginx": (None, "no container for this instance"),
        "api": (None, "no container for this instance"),
        "identity": (None, "no container for this instance"),
        "mssql": (None, "no container for this instance"),
        "lite": ("bitwarden-bitwarden-1", None),
    }


def test_lite_started_without_compose_gets_its_check_too():
    block = _block([_container("bitwarden", f"ghcr.io/bitwarden/lite:{VERSION}")])
    bound = _bind(block, "bitwarden")
    assert bound["lite"] == ("bitwarden", None)
    assert bound["api"] == (None, "no container for this instance")


@pytest.mark.parametrize(
    "image", ["vaultwarden/server:1.35.2", "ghcr.io/bitwardenx/api:1", "mariadb:10"]
)
def test_vaultwarden_and_foreign_images_are_not_taken_for_bitwarden(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize("check_key", ["nginx", "api", "identity", "mssql", "lite"])
@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ({"state": "running", "health": "starting", "restarts": 0}, "ok"),
        # Lite's image has no HEALTHCHECK.
        ({"state": "running", "health": "none", "restarts": 0}, "ok"),
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ({"state": "restarting", "health": "unhealthy", "restarts": 4}, "critical"),
        ({"state": "exited", "health": "none", "restarts": 1}, "critical"),
    ],
)
def test_each_container_check_is_critical_when_stopped_or_unhealthy(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_api_identity_nginx_database_and_lite():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("api", "health"),
        ("identity", "health"),
        ("nginx", "health"),
        ("mssql", "health"),
        ("lite", "state"),
    ]
