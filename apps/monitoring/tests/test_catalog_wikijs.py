# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module wikijs (R-1243): the image requarks/wiki under either tag, 2 or 3, and
the one of linuxserver.io get the container check and GET /favicon.ico on 3000 in plain HTTP,
the one path both versions answer; anything but 200 is critical; the database container of
the project and other images are not taken. An image tagged 2 or 2.x also gets GET /healthz
(R-1397), which Wiki.js 3 does not have."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["wikijs"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "ghcr.io/requarks/wiki:2"
# 3000 published, 3443 only exposed (EXPOSE 3000 3443).
PORTS = ((3000, 3000), (3443, None))


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


# Wiki.js with its database in one compose project, as its documentation shows it.
COMPOSE = [
    _container("docs-wiki-1", project="docs", service="wiki"),
    _container("docs-db-1", "postgres:17-alpine", "docs", "db", ((5432, None),)),
]


def _found(block):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "wikijs"}


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
        MODULE, CHECKS[check_key], "docs", _found(block)["docs"], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "web", "healthz"]
    assert MODULE.detect.container_images == [
        "requarks/wiki",
        "ghcr.io/requarks/wiki",
        "lscr.io/linuxserver/wikijs",
        "ghcr.io/linuxserver/wikijs",
        "linuxserver/wikijs",
    ]
    assert MODULE.detect.units == []
    assert all(c.credential is None for c in MODULE.checks)


def test_the_web_check_asks_the_icon_both_versions_serve_on_3000_in_plain_http():
    check = CHECKS["web"]
    assert check.sensor == "http"
    # Not /healthz: Wiki.js 3 has no such route and answers 404.
    assert check.params == {"path": "/favicon.ico", "method": "GET"}
    assert (check.target.kind, check.target.port_hint, check.target.scheme) == (
        "container",
        3000,
        "http",
    )
    assert check.fields == ["status_code"]
    assert (check.interval, check.test_object) == (300, False)


def test_the_health_check_asks_healthz_on_3000_only_for_tag_2():
    check = CHECKS["healthz"]
    assert check.sensor == "http"
    assert check.params == {"path": "/healthz", "method": "GET"}
    assert (check.target.kind, check.target.port_hint, check.target.scheme) == (
        "container",
        3000,
        "http",
    )
    assert check.image_tags == ["2", "2.*"]
    assert check.fields == ["status_code"]
    assert (check.interval, check.test_object) == (300, False)


def test_wikijs_in_its_project_gets_its_container_and_3000():
    block = _block(COMPOSE)
    assert _found(block) == {
        "docs": {
            "services": {"db": "postgres", "wiki": "ghcr.io/requarks/wiki"},
            "tag_checks": ["healthz"],
        }
    }
    assert _bind(block, "docs") == {
        "container": ("docs-wiki-1", None),
        "web": ("docs-wiki-1", None),
        "healthz": ("docs-wiki-1", None),
    }
    config, why = probe_config(
        MODULE, CHECKS["web"], "docs", _found(block)["docs"], block["containers"]
    )
    assert why is None
    assert config["target"] == {
        "kind": "container",
        "name": "docs-wiki-1",
        "port_hint": 3000,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    ("image", "ports", "tag"),
    [
        ("requarks/wiki:2", PORTS, "2"),
        ("requarks/wiki:2.5", PORTS, "2.5"),
        ("requarks/wiki:3", PORTS, "3"),
        ("ghcr.io/requarks/wiki:3.3.1", PORTS, "3.3.1"),
        ("docker.io/requarks/wiki:latest", PORTS, "latest"),
        ("ghcr.io/requarks/wiki@sha256:" + "c" * 64, PORTS, ""),
        ("lscr.io/linuxserver/wikijs:latest", ((3000, 3000),), "latest"),
        ("ghcr.io/linuxserver/wikijs:version-2.5.307", ((3000, 3000),), "version-2.5.307"),
        ("linuxserver/wikijs:2.5.307", ((3000, 3000),), "2.5.307"),
    ],
)
def test_either_version_and_either_image_get_the_container_and_3000(image, ports, tag):
    block = _block([_container("wiki", image, ports=ports)])
    bound = _bind(block, "wiki")
    assert (bound["container"], bound["web"]) == (("wiki", None), ("wiki", None))
    if tag in ("2", "2.5", "2.5.307"):
        assert bound["healthz"] == ("wiki", None)
        assert _found(block)["wiki"]["tag_checks"] == ["healthz"]
    else:
        # Wiki.js 3 answers /healthz with 404; an unknown version is not asked either.
        why = f"container wiki runs the tag {tag or '(unknown)'}, the check needs 2, 2.*"
        assert bound["healthz"] == (None, why)
        assert _found(block)["wiki"]["tag_checks"] == []


@pytest.mark.parametrize(
    "image",
    [
        "requarks/wiki-update-companion:latest",
        "ghcr.io/requarks/wiki-v2:2",
        "ghcr.io/someone/wiki:2",
        "mediawiki:1.44",
        "linuxserver/dokuwiki:latest",
    ],
)
def test_other_images_are_not_taken_for_wikijs(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"status_code": 200}, "ok", "", "ok"),
        ({"status_code": 404}, "ok", "", "critical"),
        ({"status_code": 500}, "ok", "", "critical"),
        ({"status_code": 503}, "ok", "", "critical"),
        ({}, "error", "connection refused", "critical"),
        ({}, "error", "timed out after 10s", "critical"),
    ],
)
def test_the_web_check_is_critical_on_anything_but_200(values, status, error, want):
    assert _status("web", values, status, error) == want


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"status_code": 200}, "ok", "", "ok"),
        # /healthz answers 500 when the database pool fails.
        ({"status_code": 500}, "ok", "", "critical"),
        ({}, "error", "connection refused", "critical"),
    ],
)
def test_the_health_check_is_critical_on_anything_but_200(values, status, error, want):
    assert _status("healthz", values, status, error) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "none", "restarts": 0}, "ok"),
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        # A HEALTHCHECK the compose file adds.
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ({"state": "exited", "health": "none", "restarts": 1}, "critical"),
    ],
)
def test_the_container_rules(values, want):
    assert _status("container", values) == want


def test_the_card_shows_the_container_and_the_web_check():
    assert [(i.check_key, i.field, i.label) for i in MODULE.card] == [
        ("container", "state", "Container"),
        ("container", "health", "Container health"),
        ("web", "status_code", "Web"),
    ]
