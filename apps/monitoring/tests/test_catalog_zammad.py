# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module zammad (R-1241): the compose stack's services and the package's web
unit are found, each check binds only to its variant, the health check carries the access
token in the header and never in the query, and its rules tell an unhealthy Zammad from
one that does not answer."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["zammad"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "ghcr.io/zammad/zammad:7.2.3-0000"
WEB_UNIT = "zammad-web-1.service"


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


def _container(service, image=IMAGE, ports=(), state="running"):
    name = f"zammad-{service}-1"
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": "zammad",
        "compose_service": service,
        "state": state,
        "health": "",
        "ports": [{"private": p, "public": p, "proto": "tcp"} for p in ports],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


# The services of zammad-docker-compose; the image exposes no port, only nginx is published.
COMPOSE = [
    _container("zammad-railsserver"),
    _container("zammad-scheduler"),
    _container("zammad-websocket"),
    _container("zammad-nginx", ports=[8080]),
    _container("zammad-init", state="exited"),
    _container("zammad-backup"),
    _container("zammad-postgresql", image="postgres:17.11-alpine", ports=[5432]),
    _container("zammad-redis", image="redis:8.10.3-alpine", ports=[6379]),
    _container("zammad-memcached", image="memcached:1.6.45-alpine", ports=[11211]),
    _container("zammad-elasticsearch", image="elasticsearch:9.5.5", ports=[9200, 9300]),
]
# The pkgr units of the package: zammad and zammad-web hold only a placeholder process.
PACKAGE = [
    _unit("zammad.service"),
    _unit("zammad-web.service"),
    _unit(WEB_UNIT),
    _unit("zammad-worker.service"),
    _unit("zammad-worker-1.service"),
    _unit("zammad-websocket.service"),
    _unit("zammad-websocket-1.service"),
]


def _found(block):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "zammad"}


def _bind(block, key):
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _config(check_key):
    if check_key in ("web", "web_health"):
        block, key = _block(units=PACKAGE), "zammad"
    else:
        block, key = _block(COMPOSE), "zammad"
    config, why = probe_config(MODULE, CHECKS[check_key], key, _found(block)[key], COMPOSE)
    assert why is None, why
    return config


def _status(check_key, values, status="ok"):
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**_config(check_key), "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_container_unit_and_health_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == [
        "railsserver",
        "scheduler",
        "websocket",
        "nginx",
        "health",
        "web",
        "web_health",
    ]
    for key in ("health", "web_health"):
        check = CHECKS[key]
        assert check.params == {"path": "/api/v1/monitoring/health_check", "method": "GET"}
        assert (check.interval, check.test_object) == (300, False)


def test_the_compose_stack_binds_its_services_and_the_health_check_to_the_rails_server():
    assert _bind(_block(COMPOSE), "zammad") == {
        "railsserver": ("zammad-zammad-railsserver-1", None),
        "scheduler": ("zammad-zammad-scheduler-1", None),
        "websocket": ("zammad-zammad-websocket-1", None),
        "nginx": ("zammad-zammad-nginx-1", None),
        "health": ("zammad-zammad-railsserver-1", None),
        "web": (None, "no unit for this instance"),
        "web_health": (None, "no unit for this instance"),
    }
    assert _config("health")["target"]["port_hint"] == 3000


def test_the_package_binds_the_web_unit_only():
    assert _found(_block(units=PACKAGE)) == {"zammad": {"matched_by": [f"unit:{WEB_UNIT}"]}}
    assert _bind(_block(units=PACKAGE), "zammad") == {
        "railsserver": (None, "no container for this instance"),
        "scheduler": (None, "no container for this instance"),
        "websocket": (None, "no container for this instance"),
        "nginx": (None, "no container for this instance"),
        "health": (None, "no container for this instance"),
        "web": (WEB_UNIT, None),
        "web_health": (WEB_UNIT, None),
    }
    assert _config("web_health")["target"]["port_hint"] == 3000


def test_the_token_goes_in_the_header_in_one_slot_per_variant_and_never_in_the_query():
    assert _config("health")["credential"] == {
        "ref": "zammad/zammad/default",
        "use": "header:Authorization",
    }
    assert _config("web_health")["credential"] == {
        "ref": "zammad/zammad/web",
        "use": "header:Authorization",
    }
    assert all("token" not in str(c.params).lower() for c in MODULE.checks)
    assert all(c.credential is None for c in MODULE.checks if c.sensor != "http")


@pytest.mark.parametrize(
    ("image", "found"),
    [
        ("zammad/zammad-docker-compose:7.2.3-0000", True),
        ("docker.io/zammad/zammad-docker-compose:latest", True),
        ("ghcr.io/zammad/zammad:latest", True),
        ("ghcr.io/someone/zammad:7.2", False),
        ("zammad/zammad-docker-compose-fork:1", False),
    ],
)
def test_the_image_from_either_registry_is_found_and_a_fork_is_not(image, found):
    block = _block([_container("zammad-railsserver", image=image)])
    assert ("zammad" in _found(block)) is found


@pytest.mark.parametrize("check_key", ["health", "web_health"])
@pytest.mark.parametrize(
    ("values", "status", "want"),
    [
        ({"status_code": 200, "data.healthy": True, "data.message": "success"}, "ok", "ok"),
        (
            {"status_code": 200, "data.healthy": False, "data.message": "scheduler may not run"},
            "ok",
            "warning",
        ),
        # Puma answers but Rails fails: no JSON, the status code alone decides.
        ({"status_code": 500}, "ok", "critical"),
        ({"status_code": 502}, "ok", "critical"),
        # A false that is no boolean is not Zammad's answer.
        ({"status_code": 200, "data.healthy": 0, "data.message": "success"}, "ok", "ok"),
        # A refused token or a user without admin.monitoring: the access brake, no alarm.
        ({}, "denied", "warning"),
    ],
)
def test_each_health_rule_fires_on_its_value(check_key, values, status, want):
    assert _status(check_key, values, status) == want


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("railsserver", {"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ("railsserver", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ("scheduler", {"state": "exited", "health": "none", "restarts": 0}, "critical"),
        ("websocket", {"state": "restarting", "health": "none", "restarts": 9}, "critical"),
        ("nginx", {"state": "running", "health": "none", "restarts": 2}, "ok"),
        ("web", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("web", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_the_health_of_either_variant():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("health", "data.healthy"),
        ("health", "data.message"),
        ("railsserver", "state"),
        ("web_health", "data.healthy"),
        ("web_health", "data.message"),
        ("web", "active_state"),
    ]
