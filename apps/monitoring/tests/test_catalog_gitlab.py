# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module gitlab (R-1241): the Omnibus image is found in a compose project and
without one and gets its container check only; the package's runit unit gets the unit
check and puma's readiness and liveness on 8080; a 404 of the monitoring allowlist is a
warning, a failing dependency critical."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["gitlab"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "gitlab/gitlab-ee:18.5.1-ee.0"
UNIT = "gitlab-runsvdir.service"


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
        # The image exposes 443, 80 and 22.
        "ports": [{"private": p, "public": None, "proto": "tcp"} for p in (22, 80, 443)],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


COMPOSE = [
    _container("git-gitlab-1", project="git", service="gitlab"),
    _container("git-runner-1", "gitlab/gitlab-runner:v18.5.0", "git", "runner"),
]


def _found(block):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "gitlab"}


def _bind(block, key):
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _status(check_key, values):
    if check_key == "container":
        block, key = _block(COMPOSE), "git"
    else:
        block, key = _block(units=[_unit(UNIT)]), "gitlab"
    config, why = probe_config(MODULE, CHECKS[check_key], key, _found(block)[key], COMPOSE)
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_container_unit_readiness_and_liveness():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "runsvdir", "readiness", "liveness"]
    assert CHECKS["readiness"].params == {"path": "/-/readiness?all=1", "method": "GET"}
    assert CHECKS["liveness"].params == {"path": "/-/liveness", "method": "GET"}
    for key in ("readiness", "liveness"):
        assert CHECKS[key].fields == ["status_code"]
        assert (CHECKS[key].interval, CHECKS[key].test_object) == (300, False)
        assert CHECKS[key].credential is None


def test_the_image_in_a_compose_project_gets_its_container_check_only():
    assert _found(_block(COMPOSE)) == {
        "git": {
            "services": {"gitlab": "gitlab/gitlab-ee", "runner": "gitlab/gitlab-runner"},
            "containers": {"gitlab": "git-gitlab-1", "runner": "git-runner-1"},
        }
    }
    assert _bind(_block(COMPOSE), "git") == {
        "container": ("git-gitlab-1", None),
        "runsvdir": (None, "no unit for this instance"),
        "readiness": (None, "no unit for this instance"),
        "liveness": (None, "no unit for this instance"),
    }


def test_the_image_started_without_compose_gets_its_container_check_too():
    block = _block([_container("gitlab", "gitlab/gitlab-ce:18.5.1-ce.0")])
    bound = _bind(block, "gitlab")
    assert bound["container"] == ("gitlab", None)
    assert bound["readiness"] == (None, "no unit for this instance")


def test_the_package_asks_puma_on_8080_through_its_runit_unit():
    block = _block(units=[_unit(UNIT), _unit("nginx.service", "inactive")])
    assert _found(block) == {"gitlab": {"matched_by": [f"unit:{UNIT}"]}}
    assert _bind(block, "gitlab") == {
        "container": (None, "no container for this instance"),
        "runsvdir": (UNIT, None),
        "readiness": (UNIT, None),
        "liveness": (UNIT, None),
    }
    config, _ = probe_config(MODULE, CHECKS["readiness"], "gitlab", _found(block)["gitlab"], [])
    assert config["target"] == {"kind": "unit", "name": UNIT, "port_hint": 8080, "scheme": "http"}


@pytest.mark.parametrize(
    "image", ["gitlab/gitlab-runner:latest", "ghcr.io/someone/gitlab-ce:18", "gitlab/gitaly:18"]
)
def test_the_runner_and_foreign_images_are_not_taken_for_gitlab(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize("check_key", ["readiness", "liveness"])
@pytest.mark.parametrize(
    ("code", "want"),
    [
        (200, "ok"),
        # The monitoring allowlist no longer holds 127.0.0.1: GitLab's 404 page.
        (404, "warning"),
        (503, "critical"),
        (500, "critical"),
        (502, "critical"),
    ],
)
def test_each_probe_rule_fires_on_its_status_code(check_key, code, want):
    assert _status(check_key, {"status_code": code}) == want


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("container", {"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "starting", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ("container", {"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ("runsvdir", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("runsvdir", {"active_state": "inactive", "sub_state": "dead"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_container_unit_and_both_probes():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("container", "health"),
        ("runsvdir", "active_state"),
        ("readiness", "status_code"),
        ("liveness", "status_code"),
    ]
