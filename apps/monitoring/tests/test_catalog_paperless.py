# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module paperless (R-1241): the web server container of the compose project
is found and both checks bind to it; the system status is a test object with a credential,
and ERROR is critical where documents stop coming in, a warning where the service only
degrades, and WARNING (no run recorded yet) is no problem."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["paperless"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "ghcr.io/paperless-ngx/paperless-ngx:2.18"


def _container(name, image, project, service, ports=()):
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


COMPOSE = [
    _container("docs-webserver-1", IMAGE, "docs", "webserver", ports=[8000]),
    _container("docs-broker-1", "redis:8", "docs", "broker", ports=[6379]),
    _container("docs-db-1", "postgres:17", "docs", "db", ports=[5432]),
]


def _inventory(containers):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": [],
        "sockets": [],
        "containers": containers,
        "markers": {},
        "ports": [],
    }


def _config(check_key, containers=COMPOSE):
    seen = match_inventory(_inventory(containers), CATALOG)
    return probe_config(MODULE, CHECKS[check_key], "docs", seen[("paperless", "docs")], containers)


def _status(check_key, values, status="ok"):
    config, why = _config(check_key)
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_container_and_status_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "status"]
    status = CHECKS["status"]
    assert status.params == {"path": "/api/status/", "method": "GET"}
    assert (status.interval, status.timeout_s, status.test_object) == (900, 30, True)


def test_both_checks_bind_to_the_web_server_and_the_status_carries_the_credential():
    container, _ = _config("container")
    status, _ = _config("status")
    assert container["target"]["name"] == status["target"]["name"] == "docs-webserver-1"
    assert status["target"]["port_hint"] == 8000
    assert status["credential"] == {"ref": "paperless/docs/default", "use": "header:Authorization"}
    assert container["credential"] is None


@pytest.mark.parametrize(
    ("image", "found"),
    [
        ("paperlessngx/paperless-ngx:2.18", True),
        ("docker.io/paperlessngx/paperless-ngx:latest", True),
        ("ghcr.io/someone/paperless-ngx:2.18", False),
    ],
)
def test_the_image_from_either_registry_is_found_and_a_fork_is_not(image, found):
    containers = [_container("docs-webserver-1", image, "docs", "webserver", ports=[8000])]
    seen = match_inventory(_inventory(containers), CATALOG)
    assert (("paperless", "docs") in seen) is found


def test_another_paperless_port_is_left_to_the_agent():
    """PAPERLESS_PORT moves the server; the image still exposes 8000, so the check binds."""
    moved = [_container("docs-webserver-1", IMAGE, "docs", "webserver", ports=[8000, 8010])]
    config, why = _config("status", moved)
    assert why is None and config["target"]["port_hint"] == 8000


OK_STATUS = {
    "data.pngx_version": "2.18.0",
    "data.database.status": "OK",
    "data.tasks.redis_status": "OK",
    "data.tasks.celery_status": "OK",
    "data.tasks.index_status": "OK",
    "data.tasks.classifier_status": "WARNING",
    "data.tasks.sanity_check_status": "WARNING",
}


@pytest.mark.parametrize(
    ("field", "value", "want"),
    [
        ("data.database.status", "ERROR", "critical"),
        ("data.tasks.redis_status", "ERROR", "critical"),
        ("data.tasks.celery_status", "ERROR", "critical"),
        ("data.tasks.index_status", "ERROR", "warning"),
        ("data.tasks.classifier_status", "ERROR", "warning"),
        ("data.tasks.sanity_check_status", "ERROR", "warning"),
        ("data.tasks.index_status", "WARNING", "ok"),
        ("data.tasks.classifier_status", "OK", "ok"),
    ],
)
def test_each_status_rule_fires_on_error_only(field, value, want):
    assert _status("status", {**OK_STATUS, field: value}) == want


def test_a_refused_token_is_a_warning_not_a_failure():
    assert _status("status", {}, status="denied") == "warning"


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ({"state": "running", "health": "none", "restarts": 3}, "ok"),
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ({"state": "exited", "health": "none", "restarts": 0}, "critical"),
        ({"state": "restarting", "health": "starting", "restarts": 7}, "critical"),
    ],
)
def test_the_container_rules(values, want):
    assert _status("container", values) == want


def test_the_card_shows_version_container_and_the_task_states():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("status", "data.pngx_version"),
        ("container", "state"),
        ("status", "data.database.status"),
        ("status", "data.tasks.celery_status"),
        ("status", "data.tasks.index_status"),
        ("status", "data.tasks.sanity_check_status"),
    ]
