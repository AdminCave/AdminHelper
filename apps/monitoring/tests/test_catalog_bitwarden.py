# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module bitwarden (R-1241): the standard install's nginx, api, identity and
mssql containers get their checks, whose health carries each image's own health check;
nginx's /alive is asked on the port the scan saw listening; Bitwarden Lite gets the check
of its one container."""

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


def _container(name, image, project="", service="", ports=(), listening=None):
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
        "listening": listening,
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


def test_the_module_loads_with_container_checks_and_nginx_alive():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["nginx", "api", "identity", "mssql", "lite", "alive"]
    assert {c.sensor for c in MODULE.checks} == {"container", "http"}
    assert [c.target.service for c in MODULE.checks] == [
        "nginx",
        "api",
        "identity",
        "mssql",
        "",
        "nginx",
    ]
    assert CHECKS["alive"].params["path"] == "/alive"


def test_the_standard_install_binds_each_service_and_leaves_the_lite_check_unbound():
    names = sorted(c["name"] for c in STANDARD)
    assert _bind(_block(STANDARD), "docker") == {
        "nginx": ("bitwarden-nginx", None),
        "api": ("bitwarden-api", None),
        "identity": ("bitwarden-identity", None),
        "mssql": ("bitwarden-mssql", None),
        "lite": (None, "several containers for this instance: " + ", ".join(names)),
        # The image exposes both ports; without the listening ones none is guessed.
        "alive": (
            None,
            "container bitwarden-nginx exposes several of the ports 8443, 8080, "
            "none seen listening",
        ),
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
        "alive": (None, "no container for this instance"),
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


def _alive(nginx):
    """(port_hint, scheme) of the bound alive check, or (None, why)."""
    containers = [c for c in STANDARD if c["compose_service"] != "nginx"] + [nginx]
    block = _block(containers)
    config, why = probe_config(
        MODULE, CHECKS["alive"], "docker", _found(block)["docker"], containers
    )
    return (config["target"]["port_hint"], config["target"]["scheme"]) if config else (None, why)


def _nginx(ports=(8080, 8443), listening=None):
    image = f"ghcr.io/bitwarden/nginx:{VERSION}"
    return _container("bitwarden-nginx", image, "docker", "nginx", ports, listening)


@pytest.mark.parametrize(
    ("nginx", "want"),
    [
        pytest.param(_nginx(listening=[8080, 8443]), (8443, "https"), id="tls-listening"),
        pytest.param(_nginx(listening=[8080]), (8080, "http"), id="plain-http-listening"),
        pytest.param(_nginx(ports=[8080]), (8080, "http"), id="only-8080-exposed"),
        pytest.param(_nginx(ports=[]), (8443, "https"), id="no-port-seen-takes-the-first"),
        pytest.param(
            _nginx(listening=[5000]),
            (None, "container bitwarden-nginx has none of the ports 8443, 8080"),
            id="neither-listening",
        ),
        pytest.param(
            _nginx(ports=[80]),
            (None, "container bitwarden-nginx has none of the ports 8443, 8080"),
            id="neither-exposed",
        ),
    ],
)
def test_nginx_alive_takes_the_first_port_the_scan_saw(nginx, want):
    assert _alive(nginx) == want


@pytest.mark.parametrize(("code", "want"), [(200, "ok"), (301, "critical"), (502, "critical")])
def test_nginx_alive_is_critical_on_any_answer_but_200(code, want):
    containers = [c for c in STANDARD if c["compose_service"] != "nginx"]
    containers.append(_nginx(listening=[8080, 8443]))
    block = _block(containers)
    config, why = probe_config(
        MODULE, CHECKS["alive"], "docker", _found(block)["docker"], containers
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": {"status_code": code}}
    report = {"timestamp": STAMP, "probes": {"chk": {**result, "error": ""}}}
    assert ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0] == want


def test_the_card_shows_api_identity_nginx_database_and_lite():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("api", "health"),
        ("identity", "health"),
        ("nginx", "health"),
        ("mssql", "health"),
        ("lite", "state"),
    ]
