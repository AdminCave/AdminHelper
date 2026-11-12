# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module frigate (R-1241): the image gets its container check and both stats
checks on the internal port 5000, never the login port 8971; the stats report fixed fields
only, a dead set of cameras is a warning and a Frigate without total camera frames (before
0.17) leaves that check unknown."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["frigate"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "ghcr.io/blakeblackshear/frigate:0.17.2"
RECORDINGS = "data.service.storage./media/frigate/recordings.free"


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


def _container(name, image=IMAGE, project="", service=""):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": "healthy",
        # The image exposes 5000, 8554 and 8555; the compose file of the docs publishes 8971.
        "ports": [{"private": p, "public": None, "proto": "tcp"} for p in (5000, 8554, 8555, 8971)],
        "mounts": [],
    }


COMPOSE = [_container("frigate", project="nvr", service="frigate")]


def _found(block):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "frigate"}


def _status(check_key, values):
    block = _block(COMPOSE)
    config, why = probe_config(MODULE, CHECKS[check_key], "nvr", _found(block)["nvr"], COMPOSE)
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_container_stats_and_cameras():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "stats", "cameras"]
    for key in ("stats", "cameras"):
        assert CHECKS[key].params == {"path": "/api/stats", "method": "GET"}
        assert (CHECKS[key].interval, CHECKS[key].test_object) == (300, False)
        assert CHECKS[key].credential is None
    assert CHECKS["stats"].fields == [
        "status_code",
        "data.service.version",
        "data.service.uptime",
        "data.detection_fps",
        RECORDINGS,
    ]
    assert CHECKS["cameras"].fields == ["data.camera_fps"]


@pytest.mark.parametrize("block_key", ["compose", "plain"])
def test_the_image_gets_all_three_checks_on_the_internal_port(block_key):
    if block_key == "compose":
        block, key = _block(COMPOSE), "nvr"
        assert _found(block) == {
            "nvr": {"services": {"frigate": "ghcr.io/blakeblackshear/frigate"}}
        }
    else:
        block, key = (
            _block([_container("frigate", "ghcr.io/blakeblackshear/frigate:0.16.4-tensorrt")]),
            "frigate",
        )
    summary = _found(block)[key]
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, key, summary, block["containers"])
        assert why is None, why
        assert config["target"]["name"] == "frigate"
    config, _ = probe_config(MODULE, CHECKS["stats"], key, summary, block["containers"])
    assert config["target"] == {
        "kind": "container",
        "name": "frigate",
        "port_hint": 5000,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/someone/frigate:0.17",
        "ghcr.io/blakeblackshear/frigate-proxy:1",
        "eclipse-mosquitto:2",
    ],
)
def test_foreign_images_are_not_taken_for_frigate(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize(
    ("values", "want"),
    [
        (
            {"status_code": 200, "data.service.version": "0.17.2-6f5d4a1", RECORDINGS: 812345.6},
            "ok",
        ),
        # The recordings directory is full: Frigate deletes old recordings itself.
        ({"status_code": 200, RECORDINGS: 0.0}, "ok"),
        ({"status_code": 500}, "critical"),
        ({"status_code": 401}, "critical"),
    ],
)
def test_the_stats_check_is_critical_without_a_200_only(values, want):
    assert _status("stats", values) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"data.camera_fps": 25.03}, "ok"),
        ({"data.camera_fps": 0.1}, "ok"),
        ({"data.camera_fps": 0.05}, "warning"),
        ({"data.camera_fps": 0}, "warning"),
        # Frigate 0.16 and older report no total of camera frames.
        ({}, "unknown"),
    ],
)
def test_the_cameras_check_warns_when_no_camera_delivers_frames(values, want):
    assert _status("cameras", values) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        ({"state": "running", "health": "starting", "restarts": 0}, "ok"),
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ({"state": "exited", "health": "none", "restarts": 1}, "critical"),
    ],
)
def test_the_container_rules(values, want):
    assert _status("container", values) == want


def test_the_card_shows_health_version_cameras_detections_and_free_space():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "health"),
        ("stats", "data.service.version"),
        ("cameras", "data.camera_fps"),
        ("stats", "data.detection_fps"),
        ("stats", RECORDINGS),
    ]
