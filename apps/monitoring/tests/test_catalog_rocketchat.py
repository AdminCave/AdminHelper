# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module rocketchat (R-1242): the three images get the container check and
/livez on 3000, as none has a HEALTHCHECK; the snap's unit and rocketchat.service get the
unit check and /livez on 3000; /livez rates MongoDB critical and memory and event loop as a
warning; the microservices and MongoDB are not Rocket.Chat."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["rocketchat"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "registry.rocket.chat/rocketchat/rocket.chat:8.9.1"
SNAP = "snap.rocketchat-server.rocketchat-server.service"
UNIT = "rocketchat.service"


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


def _container(name, image=IMAGE, project="", service="", ports=((3000, "tcp"),)):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        # None of the images has a HEALTHCHECK.
        "health": "none",
        "ports": [{"private": p, "public": p, "proto": proto} for p, proto in ports],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


# Rocket.Chat's compose file: the server publishes 3000 and its metrics on 9458.
COMPOSE = [
    _container(
        "rocketchat-rocketchat-1",
        project="rocketchat",
        service="rocketchat",
        ports=[(3000, "tcp"), (9458, "tcp")],
    ),
    _container(
        "rocketchat-mongodb-1",
        "mongodb/mongodb-community-server:8.2-ubi8",
        "rocketchat",
        "mongodb",
        [(27017, "tcp")],
    ),
    _container("rocketchat-nats-1", "nats:2.11-alpine", "rocketchat", "nats", [(4222, "tcp")]),
]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "rocketchat"
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
    if CHECKS[check_key].target.kind == "container":
        block, key = _block(COMPOSE), "rocketchat"
    else:
        block, key = _block(units=[_unit(SNAP)]), "rocketchat"
    config, why = probe_config(
        MODULE, CHECKS[check_key], key, _found(block)[key], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "livez", "service", "service_livez"]
    assert MODULE.detect.units == [SNAP, UNIT]
    assert all(c.credential is None for c in MODULE.checks)


def test_both_http_checks_ask_livez_only():
    for key in ("livez", "service_livez"):
        assert CHECKS[key].params == {"path": "/livez", "method": "GET"}
        assert CHECKS[key].fields == [
            "status_code",
            "data.checks.mongo.status",
            "data.checks.memory.status",
            "data.checks.eventLoop.status",
        ]
        assert (CHECKS[key].interval, CHECKS[key].test_object) == (300, False)


def test_the_project_gets_the_container_and_livez_on_3000():
    block = _block(COMPOSE)
    assert _found(block) == {
        "rocketchat": {
            "services": {
                "rocketchat": "registry.rocket.chat/rocketchat/rocket.chat",
                "mongodb": "mongodb/mongodb-community-server",
                "nats": "nats",
            },
            "containers": {
                "mongodb": "rocketchat-mongodb-1",
                "nats": "rocketchat-nats-1",
                "rocketchat": "rocketchat-rocketchat-1",
            },
        }
    }
    assert _bind(block, "rocketchat") == {
        "container": ("rocketchat-rocketchat-1", None),
        "livez": ("rocketchat-rocketchat-1", None),
        "service": (None, "no unit for this instance"),
        "service_livez": (None, "no unit for this instance"),
    }
    # The metrics port is published as well; the hint picks 3000.
    assert _target("livez", block, "rocketchat") == {
        "kind": "container",
        "name": "rocketchat-rocketchat-1",
        "port_hint": 3000,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    "image",
    [
        "rocketchat/rocket.chat:8.9.1",
        "docker.io/rocketchat/rocket.chat:latest",
        "rocket.chat:8.9.1",
        "docker.io/library/rocket.chat:8.9",
        "registry.rocket.chat/rocketchat/rocket.chat@sha256:" + "b" * 64,
    ],
)
def test_each_image_started_without_compose_gets_the_container_and_livez(image):
    block = _block([_container("rocketchat", image)])
    bound = _bind(block, "rocketchat")
    assert (bound["container"], bound["livez"]) == (("rocketchat", None), ("rocketchat", None))


@pytest.mark.parametrize("unit", [SNAP, UNIT])
def test_the_snap_and_the_manual_install_get_their_unit_and_livez_on_3000(unit):
    block = _block(units=[_unit(unit), _unit("mongod.service"), _unit("nginx.service")])
    assert _found(block) == {"rocketchat": {"matched_by": [f"unit:{unit}"]}}
    assert _bind(block, "rocketchat") == {
        "container": (None, "no container for this instance"),
        "livez": (None, "no container for this instance"),
        "service": (unit, None),
        "service_livez": (unit, None),
    }
    assert _target("service_livez", block, "rocketchat") == {
        "kind": "unit",
        "name": unit,
        "port_hint": 3000,
        "scheme": "http",
    }


def test_the_snaps_mongodb_and_caddy_alone_are_not_rocketchat():
    block = _block(
        units=[
            _unit("snap.rocketchat-server.rocketchat-mongo.service"),
            _unit("snap.rocketchat-server.rocketchat-caddy.service"),
        ]
    )
    assert _found(block) == {}


@pytest.mark.parametrize(
    "image",
    [
        "rocketchat/authorization-service:8.9.1",
        "rocketchat/ddp-streamer-service:8.9.1",
        "mongodb/mongodb-community-server:8.2-ubi8",
        "someone/rocket.chat:1",
    ],
)
def test_other_images_are_not_taken_for_rocketchat(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


def _livez(code, mongo="ok", memory="ok", event_loop="ok"):
    return {
        "status_code": code,
        "data.checks.mongo.status": mongo,
        "data.checks.memory.status": memory,
        "data.checks.eventLoop.status": event_loop,
    }


@pytest.mark.parametrize("check_key", ["livez", "service_livez"])
@pytest.mark.parametrize(
    ("values", "want"),
    [
        (_livez(200), "ok"),
        (_livez(503, mongo="degraded"), "critical"),
        # Up to 8.0 the heap test passes on a healthy server between two collections.
        (_livez(503, memory="degraded"), "warning"),
        (_livez(503, event_loop="degraded"), "warning"),
        (_livez(503, memory="degraded", event_loop="degraded"), "warning"),
        (_livez(503, mongo="degraded", memory="degraded"), "critical"),
        # A JSON answer without the checks (not /livez): nothing to rate.
        ({"status_code": 404}, "unknown"),
    ],
)
def test_livez_rates_mongodb_critical_and_load_as_a_warning(check_key, values, want):
    assert _status(check_key, values) == want


def test_an_answer_that_is_no_json_object_fails_the_check():
    # Before 7.11.0 there is no /livez; the agent fails the probe instead of passing it.
    assert _status("livez", {}, "error", "the answer is no JSON object") == "critical"


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("container", {"state": "running", "health": "none", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ("container", {"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ("container", {"state": "restarting", "health": "none", "restarts": 4}, "critical"),
        ("service", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_the_container_or_the_service_and_mongodb():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("livez", "data.checks.mongo.status"),
        ("service", "active_state"),
        ("service_livez", "data.checks.mongo.status"),
    ]
