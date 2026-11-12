# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module gitea (R-1243): the images of Gitea and Forgejo get the container check
and GET /api/healthz on 3000 in plain HTTP; the units gitea.service and forgejo.service get
the unit check and the same; anything but 200 is critical, a database or cache that does not
answer (424) too; the database container of the project, the runners and other images are
not taken."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["gitea"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "docker.gitea.com/gitea:1.25"
# 3000 and SSH published (EXPOSE 22 3000; the rootless images 2222 3000).
PORTS = ((22, 2222), (3000, 3000))


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


# Gitea with its database and a runner in one compose project.
COMPOSE = [
    _container("git-server-1", project="git", service="server"),
    _container("git-db-1", "postgres:17", "git", "db", ((5432, None),)),
    _container("git-runner-1", "docker.gitea.com/act_runner:0.2", "git", "runner", ()),
]


def _found(block):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "gitea"}


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
        block, key = _block(COMPOSE), "git"
    else:
        block, key = _block(units=[_unit("forgejo.service")]), "gitea"
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
    assert MODULE.detect.container_images == [
        "docker.gitea.com/gitea",
        "gitea/gitea",
        "codeberg.org/forgejo/forgejo",
        "data.forgejo.org/forgejo/forgejo",
    ]
    assert MODULE.detect.units == ["gitea.service", "forgejo.service"]
    assert all(c.credential is None for c in MODULE.checks)


def test_both_health_checks_ask_healthz_on_3000_in_plain_http():
    for key in ("health", "service_health"):
        check = CHECKS[key]
        assert check.sensor == "http"
        assert check.params == {"path": "/api/healthz", "method": "GET"}
        assert (check.target.port_hint, check.target.scheme) == (3000, "http")
        assert check.fields == ["status_code"]
        assert (check.interval, check.test_object) == (300, False)


def test_gitea_in_its_project_gets_its_container_and_3000():
    block = _block(COMPOSE)
    services = {
        "db": "postgres",
        "runner": "docker.gitea.com/act_runner",
        "server": "docker.gitea.com/gitea",
    }
    assert _found(block) == {"git": {"services": services}}
    assert _bind(block, "git") == {
        "container": ("git-server-1", None),
        "health": ("git-server-1", None),
        "service": (None, "no unit for this instance"),
        "service_health": (None, "no unit for this instance"),
    }
    assert _target("health", block, "git") == {
        "kind": "container",
        "name": "git-server-1",
        "port_hint": 3000,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    "image",
    [
        "docker.gitea.com/gitea:1.25-rootless",
        "gitea/gitea:latest",
        "docker.io/gitea/gitea:1.24",
        "codeberg.org/forgejo/forgejo:13",
        "data.forgejo.org/forgejo/forgejo:13-rootless",
        "gitea/gitea@sha256:" + "c" * 64,
    ],
)
def test_the_images_of_gitea_and_forgejo_get_the_container_and_3000(image):
    block = _block([_container("gitea", image)])
    bound = _bind(block, "gitea")
    assert (bound["container"], bound["health"]) == (("gitea", None), ("gitea", None))


@pytest.mark.parametrize("unit", ["gitea.service", "forgejo.service"])
def test_each_unit_gets_the_unit_check_and_3000(unit):
    block = _block(units=[_unit(unit), _unit("postgresql.service"), _unit("nginx.service")])
    assert _found(block) == {"gitea": {"matched_by": [f"unit:{unit}"]}}
    assert _bind(block, "gitea") == {
        "container": (None, "no container for this instance"),
        "health": (None, "no container for this instance"),
        "service": (unit, None),
        "service_health": (unit, None),
    }
    assert _target("service_health", block, "gitea") == {
        "kind": "unit",
        "name": unit,
        "port_hint": 3000,
        "scheme": "http",
    }


def test_both_units_on_one_host_bind_neither():
    # A host on its way from Gitea to Forgejo: which of the two serves 3000 is not known.
    block = _block(units=[_unit("gitea.service"), _unit("forgejo.service")])
    bound = _bind(block, "gitea")
    assert bound["service"] == (None, "no unit for this instance")
    assert bound["service_health"] == (None, "no unit for this instance")


@pytest.mark.parametrize(
    "unit", ["gitea-runner.service", "forgejo-runner.service", "act_runner.service"]
)
def test_the_units_of_the_runners_are_not_taken(unit):
    assert _found(_block(units=[_unit(unit)])) == {}


@pytest.mark.parametrize(
    "image",
    [
        "gitea/act_runner:0.2",
        "docker.gitea.com/act_runner:nightly",
        "code.forgejo.org/forgejo/runner:11",
        "data.forgejo.org/forgejo/runner:11",
        "bitnami/gitea:1.25",
        "ghcr.io/someone/gitea:1",
        "codeberg.org/forgejo-contrib/forgejo-helm:1",
    ],
)
def test_runners_and_other_images_are_not_taken(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize("check_key", ["health", "service_health"])
@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"status_code": 200}, "ok", "", "ok"),
        # The database or the cache does not answer.
        ({"status_code": 424}, "ok", "", "critical"),
        ({"status_code": 500}, "ok", "", "critical"),
        # PROTOCOL = https answers the plain request with 400.
        ({"status_code": 400}, "ok", "", "critical"),
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
