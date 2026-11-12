# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module home-assistant (R-1243): the image of Home Assistant and the one of
linuxserver.io get the container check and GET / on 8123 in plain HTTP without credentials,
also on the host's network, where the scan sees no ports; anything but 200 is critical, a ban
of the agent's address too; the images of Home Assistant OS and Supervised and other images
are not taken."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["home-assistant"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "ghcr.io/home-assistant/home-assistant:stable"


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


def _container(name, image=IMAGE, project="", service="", ports=()):
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


# The compose file of the installation guide: network_mode host, so the scan sees no ports.
COMPOSE = [_container("homeassistant", project="ha", service="homeassistant")]


def _found(block):
    return {
        key: s
        for (mid, key), s in match_inventory(block, CATALOG).items()
        if mid == "home-assistant"
    }


def _bind(block, key):
    summary = _found(block)[key]
    bound = {}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        bound[check.key] = (config["target"]["name"], None) if config else (None, why)
    return bound


def _status(check_key, values, status="ok", error=""):
    block = _block(COMPOSE)
    config, why = probe_config(
        MODULE, CHECKS[check_key], "ha", _found(block)["ha"], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "frontend"]
    assert MODULE.detect.container_images == [
        "ghcr.io/home-assistant/home-assistant",
        "homeassistant/home-assistant",
        "lscr.io/linuxserver/homeassistant",
        "ghcr.io/linuxserver/homeassistant",
        "linuxserver/homeassistant",
    ]
    assert MODULE.detect.units == []


def test_no_check_carries_a_credential_or_asks_the_api():
    # Each 401 raises a notification in Home Assistant and counts towards a ban.
    assert all(c.credential is None for c in MODULE.checks)
    assert [c.params["path"] for c in MODULE.checks if c.sensor == "http"] == ["/"]


def test_the_frontend_check_asks_the_root_on_8123_in_plain_http():
    check = CHECKS["frontend"]
    assert check.sensor == "http"
    assert check.params == {"path": "/", "method": "GET"}
    assert (check.target.kind, check.target.port_hint, check.target.scheme) == (
        "container",
        8123,
        "http",
    )
    assert check.fields == ["status_code"]
    assert (check.interval, check.test_object) == (300, False)


def test_the_container_on_the_hosts_network_gets_its_container_and_8123():
    block = _block(COMPOSE)
    assert _found(block) == {
        "ha": {"services": {"homeassistant": "ghcr.io/home-assistant/home-assistant"}}
    }
    assert _bind(block, "ha") == {
        "container": ("homeassistant", None),
        "frontend": ("homeassistant", None),
    }
    config, why = probe_config(
        MODULE, CHECKS["frontend"], "ha", _found(block)["ha"], block["containers"]
    )
    assert why is None
    # The agent finds 8123 among the sockets of the container's processes.
    assert config["target"] == {
        "kind": "container",
        "name": "homeassistant",
        "port_hint": 8123,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    ("image", "ports"),
    [
        ("ghcr.io/home-assistant/home-assistant:2026.11.1", ()),
        ("homeassistant/home-assistant:stable", ()),
        ("docker.io/homeassistant/home-assistant:latest", ()),
        ("ghcr.io/home-assistant/home-assistant@sha256:" + "e" * 64, ()),
        # Published on a bridge network instead.
        ("ghcr.io/home-assistant/home-assistant:stable", ((8123, 8123),)),
        ("lscr.io/linuxserver/homeassistant:latest", ((8123, 8123),)),
        ("ghcr.io/linuxserver/homeassistant:2026.11.1", ()),
        ("linuxserver/homeassistant:latest", ()),
    ],
)
def test_either_image_on_either_network_gets_the_container_and_8123(image, ports):
    bound = _bind(_block([_container("homeassistant", image, ports=ports)]), "homeassistant")
    assert bound == {"container": ("homeassistant", None), "frontend": ("homeassistant", None)}


def test_a_container_that_lacks_8123_is_not_asked():
    block = _block([_container("homeassistant", ports=((8080, 8080),))])
    bound = _bind(block, "homeassistant")
    assert bound["container"] == ("homeassistant", None)
    assert bound["frontend"][0] is None


@pytest.mark.parametrize(
    "image",
    [
        # Home Assistant OS and Supervised: an image per machine, and the supervisor.
        "ghcr.io/home-assistant/qemux86-64-homeassistant:2026.11.1",
        "ghcr.io/home-assistant/amd64-hassio-supervisor:latest",
        "ghcr.io/home-assistant/home-assistant-fork:1",
        "homeassistant/home-assistant-fork:1",
        "ghcr.io/esphome/esphome:stable",
        "koenkk/zigbee2mqtt:latest",
    ],
)
def test_other_images_are_not_taken_for_home_assistant(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"status_code": 200}, "ok", "", "ok"),
        ({"status_code": 404}, "ok", "", "critical"),
        ({"status_code": 500}, "ok", "", "critical"),
        ({"status_code": 502}, "ok", "", "critical"),
        # The agent's address is on the ban list: Home Assistant refuses every request.
        ({}, "error", "access denied: HTTP 403", "critical"),
        ({}, "error", "connection refused", "critical"),
        ({}, "error", "timed out after 10s", "critical"),
        # On the host's network with another server_port and further sockets.
        ({}, "ambiguous_target", "container homeassistant listens on ports 8300, 21063", "unknown"),
    ],
)
def test_the_frontend_check_is_critical_on_anything_but_200(values, status, error, want):
    assert _status("frontend", values, status, error) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "none", "restarts": 0}, "ok"),
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        # A HEALTHCHECK the compose file adds.
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ({"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ({"state": "restarting", "health": "none", "restarts": 5}, "critical"),
    ],
)
def test_the_container_rules(values, want):
    assert _status("container", values) == want


def test_the_card_shows_the_container_and_the_frontend():
    assert [(i.check_key, i.field, i.label) for i in MODULE.card] == [
        ("container", "state", "Container"),
        ("container", "health", "Container health"),
        ("frontend", "status_code", "Frontend"),
    ]
