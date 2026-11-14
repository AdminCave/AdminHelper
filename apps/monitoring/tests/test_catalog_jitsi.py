# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules jitsi-videobridge and jitsi-jicofo (R-1242): docker-jitsi-meet's
project gets the bridge's container and /about/health on 8080 and Jicofo's container; the
packages get their units and /about/health on 8080 and 8888; a bridge on a host of its own
is no Jicofo; no check asks anything but /about/health."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
JVB = CATALOG.modules["jitsi-videobridge"]
JICOFO = CATALOG.modules["jitsi-jicofo"]
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
TAG = "stable-10314"
JVB_UNIT = "jitsi-videobridge2.service"
JICOFO_UNIT = "jicofo.service"


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


def _container(name, image, project="", service="", ports=()):
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


# docker-jitsi-meet's compose file: the bridge publishes 8080 and Jicofo 8888 on 127.0.0.1.
COMPOSE = [
    _container("meet-web-1", f"ghcr.io/jitsi/web:{TAG}", "meet", "web", [(80, "tcp")]),
    _container("meet-prosody-1", f"ghcr.io/jitsi/prosody:{TAG}", "meet", "prosody"),
    _container("meet-jicofo-1", f"ghcr.io/jitsi/jicofo:{TAG}", "meet", "jicofo", [(8888, "tcp")]),
    _container(
        "meet-jvb-1",
        f"ghcr.io/jitsi/jvb:{TAG}",
        "meet",
        "jvb",
        [(10000, "udp"), (8080, "tcp")],
    ),
]
SERVICES = {
    "web": "ghcr.io/jitsi/web",
    "prosody": "ghcr.io/jitsi/prosody",
    "jicofo": "ghcr.io/jitsi/jicofo",
    "jvb": "ghcr.io/jitsi/jvb",
}
# The packages of jitsi-meet on one host.
PACKAGES = [_unit(JVB_UNIT), _unit(JICOFO_UNIT), _unit("prosody.service"), _unit("nginx.service")]


def _found(module, block):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == module.id}


def _bind(module, block, key):
    summary = _found(module, block)[key]
    bound = {}
    for check in module.checks:
        config, why = probe_config(module, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _target(module, check_key, block, key):
    check = next(c for c in module.checks if c.key == check_key)
    config, why = probe_config(module, check, key, _found(module, block)[key], block["containers"])
    assert why is None, why
    return config["target"]


def _status(module, check_key, values):
    check = next(c for c in module.checks if c.key == check_key)
    if check.target.kind == "container":
        block, key = _block(COMPOSE), "meet"
    else:
        block, key = _block(units=PACKAGES), module.id
    config, why = probe_config(module, check, key, _found(module, block)[key], block["containers"])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_modules_load_with_their_checks():
    assert CATALOG.errors == ()
    assert [c.key for c in JVB.checks] == ["container", "health", "service", "service_health"]
    assert [c.key for c in JICOFO.checks] == ["container", "service", "health"]
    assert JVB.detect.units == [JVB_UNIT]
    assert JICOFO.detect.units == [JICOFO_UNIT]
    assert all(c.credential is None for c in JVB.checks + JICOFO.checks)


def test_no_check_asks_anything_but_about_health():
    # Jicofo's server also answers /move-endpoints (moves participants), /debug, /pin and
    # /stats; the bridge's /colibri/stats is off by default.
    http = [c for c in JVB.checks + JICOFO.checks if c.sensor == "http"]
    assert len(http) == 3
    for check in http:
        assert check.params == {"path": "/about/health", "method": "GET"}
        assert check.fields == ["status_code"]
        assert (check.interval, check.test_object) == (300, False)


def test_the_project_gets_the_bridge_container_and_its_health_on_8080():
    block = _block(COMPOSE)
    assert _found(JVB, block) == {
        "meet": {
            "services": SERVICES,
            "containers": {
                "jicofo": "meet-jicofo-1",
                "jvb": "meet-jvb-1",
                "prosody": "meet-prosody-1",
                "web": "meet-web-1",
            },
        }
    }
    assert _bind(JVB, block, "meet") == {
        "container": ("meet-jvb-1", None),
        "health": ("meet-jvb-1", None),
        "service": (None, "no unit for this instance"),
        "service_health": (None, "no unit for this instance"),
    }
    assert _target(JVB, "health", block, "meet") == {
        "kind": "container",
        "name": "meet-jvb-1",
        "port_hint": 8080,
        "scheme": "http",
    }


def test_the_project_gets_jicofos_container_only():
    # Jicofo's REST server stays on the container's loopback without JICOFO_ENABLE_REST.
    block = _block(COMPOSE)
    assert _found(JICOFO, block) == {
        "meet": {
            "services": SERVICES,
            "containers": {
                "jicofo": "meet-jicofo-1",
                "jvb": "meet-jvb-1",
                "prosody": "meet-prosody-1",
                "web": "meet-web-1",
            },
        }
    }
    assert _bind(JICOFO, block, "meet") == {
        "container": ("meet-jicofo-1", None),
        "service": (None, "no unit for this instance"),
        "health": (None, "no unit for this instance"),
    }


def test_the_packages_get_their_units_and_health_on_8080_and_8888():
    block = _block(units=PACKAGES)
    assert _found(JVB, block) == {"jitsi-videobridge": {"matched_by": [f"unit:{JVB_UNIT}"]}}
    assert _bind(JVB, block, "jitsi-videobridge") == {
        "container": (None, "no container for this instance"),
        "health": (None, "no container for this instance"),
        "service": (JVB_UNIT, None),
        "service_health": (JVB_UNIT, None),
    }
    assert _target(JVB, "service_health", block, "jitsi-videobridge") == {
        "kind": "unit",
        "name": JVB_UNIT,
        "port_hint": 8080,
        "scheme": "http",
    }
    assert _found(JICOFO, block) == {"jitsi-jicofo": {"matched_by": [f"unit:{JICOFO_UNIT}"]}}
    assert _bind(JICOFO, block, "jitsi-jicofo") == {
        "container": (None, "no container for this instance"),
        "service": (JICOFO_UNIT, None),
        "health": (JICOFO_UNIT, None),
    }
    assert _target(JICOFO, "health", block, "jitsi-jicofo") == {
        "kind": "unit",
        "name": JICOFO_UNIT,
        "port_hint": 8888,
        "scheme": "http",
    }


def test_a_bridge_on_a_host_of_its_own_is_no_jicofo():
    block = _block(units=[_unit(JVB_UNIT)])
    assert list(_found(JVB, block)) == ["jitsi-videobridge"]
    assert _found(JICOFO, block) == {}
    block = _block([_container("jvb", f"ghcr.io/jitsi/jvb:{TAG}", ports=[(8080, "tcp")])])
    assert _bind(JVB, block, "jvb")["health"] == ("jvb", None)
    assert _found(JICOFO, block) == {}


@pytest.mark.parametrize(
    ("module", "image"),
    [
        (JVB, "jitsi/jvb:stable-9823"),
        (JVB, "docker.io/jitsi/jvb:stable-9823"),
        (JICOFO, "jitsi/jicofo:stable-9823"),
    ],
)
def test_the_old_docker_hub_images_are_taken_too(module, image):
    assert list(_found(module, _block([_container("x", image)]))) == ["x"]


@pytest.mark.parametrize(
    "image",
    [
        f"ghcr.io/jitsi/web:{TAG}",
        f"ghcr.io/jitsi/prosody:{TAG}",
        "jitsi/jibri:stable-9823",
        "ghcr.io/someone/jvb:1",
    ],
)
def test_the_other_images_of_jitsi_are_neither(image):
    block = _block([_container("x", image, "x", "x")])
    assert _found(JVB, block) == {}
    assert _found(JICOFO, block) == {}


def test_prosody_and_nginx_alone_are_neither():
    block = _block(units=[_unit("prosody.service"), _unit("nginx.service")])
    assert _found(JVB, block) == {}
    assert _found(JICOFO, block) == {}


@pytest.mark.parametrize(
    ("module", "check_key", "code", "want"),
    [
        (JVB, "health", 200, "ok"),
        (JVB, "health", 500, "critical"),
        (JVB, "service_health", 200, "ok"),
        (JVB, "service_health", 500, "critical"),
        (JICOFO, "health", 200, "ok"),
        # No operational bridge: Jicofo's health check fails hard.
        (JICOFO, "health", 500, "critical"),
        (JICOFO, "health", 503, "critical"),
    ],
)
def test_health_is_critical_on_anything_but_200(module, check_key, code, want):
    assert _status(module, check_key, {"status_code": code}) == want


@pytest.mark.parametrize("module", [JVB, JICOFO])
@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("container", {"state": "running", "health": "none", "restarts": 0}, "ok"),
        ("container", {"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ("container", {"state": "restarting", "health": "none", "restarts": 4}, "critical"),
        ("service", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(module, check_key, values, want):
    assert _status(module, check_key, values) == want


def test_the_cards_show_the_container_or_the_service_and_health():
    assert [(i.check_key, i.field) for i in JVB.card] == [
        ("container", "state"),
        ("health", "status_code"),
        ("service", "active_state"),
        ("service_health", "status_code"),
    ]
    assert [(i.check_key, i.field) for i in JICOFO.card] == [
        ("container", "state"),
        ("service", "active_state"),
        ("health", "status_code"),
    ]
