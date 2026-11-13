# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module wordpress (R-1243, R-1404): the official image gets the container
check, GET /?rest_route=/ on port 80 in plain HTTP every five minutes and the version from
the container once an hour; anything but 200 is critical, a refused REST API is the access
brake, the version is shown and not rated; the fpm variant gets no HTTP check but the
version, a second container of the image leaves the project unbound, a WordPress on the
host and other images are not taken; no check asks wp-cron.php."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["wordpress"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "wordpress:6.8.3-php8.3-apache"


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


def _container(name, image=IMAGE, project="", service="", ports=((80, 8080),)):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        # The image has no HEALTHCHECK of its own.
        "health": "none",
        "ports": [{"private": p, "public": pub, "proto": "tcp"} for p, pub in ports],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


# WordPress with its database in one compose project.
COMPOSE = [
    _container("blog-wordpress-1", project="blog", service="wordpress"),
    _container("blog-db-1", "mariadb:11", "blog", "db", ((3306, None),)),
]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "wordpress"
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
    config, why = probe_config(
        MODULE, CHECKS[check_key], "blog", _found(_block(COMPOSE))["blog"], COMPOSE
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert MODULE.version == 2
    assert list(CHECKS) == ["container", "rest", "version"]
    assert MODULE.detect.container_images == ["wordpress"]
    assert (MODULE.detect.units, MODULE.detect.processes) == ([], [])
    assert all(c.credential is None for c in MODULE.checks)


def test_the_rest_check_asks_the_query_form_on_80_in_plain_http_every_five_minutes():
    # /wp-json/ needs pretty permalinks; the query form is served before the canonical redirect.
    check = CHECKS["rest"]
    assert check.sensor == "http"
    assert check.params == {"path": "/?rest_route=/", "method": "GET"}
    assert (check.target.kind, check.target.port_hint, check.target.scheme) == (
        "container",
        80,
        "http",
    )
    assert check.fields == ["status_code"]
    assert (check.interval, check.test_object) == (300, False)


def test_no_check_asks_the_cron_or_the_admin():
    for check in MODULE.checks:
        path = (check.params or {}).get("path", "")
        assert "cron" not in path and "admin" not in path and "xmlrpc" not in path


def test_wordpress_in_its_project_gets_its_container_and_80():
    block = _block(COMPOSE)
    assert _found(block) == {"blog": {"services": {"db": "mariadb", "wordpress": "wordpress"}}}
    assert _bind(block, "blog") == {
        "container": ("blog-wordpress-1", None),
        "rest": ("blog-wordpress-1", None),
        "version": ("blog-wordpress-1", None),
    }
    assert _target("rest", block, "blog") == {
        "kind": "container",
        "name": "blog-wordpress-1",
        "port_hint": 80,
        "scheme": "http",
    }


@pytest.mark.parametrize(
    "image",
    [
        "wordpress:latest",
        "wordpress:6-apache",
        "docker.io/library/wordpress:6.8",
        "library/wordpress:php8.4",
        "wordpress@sha256:" + "a" * 64,
    ],
)
def test_the_image_started_without_compose_gets_the_container_and_80(image):
    block = _block([_container("wordpress", image, ports=((80, None),))])
    assert _bind(block, "wordpress") == {
        "container": ("wordpress", None),
        "rest": ("wordpress", None),
        "version": ("wordpress", None),
    }


def test_the_fpm_variant_serves_no_http_and_gets_the_container_check_and_the_version():
    block = _block(
        [
            _container("blog-wordpress-1", "wordpress:6-fpm", "blog", "wordpress", ((9000, None),)),
            _container("blog-web-1", "nginx:1.29", "blog", "web", ((80, 8080),)),
        ]
    )
    assert _bind(block, "blog") == {
        "container": ("blog-wordpress-1", None),
        "rest": (None, "container blog-wordpress-1 has no port 80"),
        "version": ("blog-wordpress-1", None),
    }


def test_a_cli_container_next_to_the_site_leaves_the_project_unbound():
    block = _block([*COMPOSE, _container("blog-cli-1", "wordpress:cli", "blog", "cli", ())])
    why = "several containers for this instance: blog-cli-1, blog-wordpress-1"
    assert _bind(block, "blog") == {
        "container": (None, why),
        "rest": (None, why),
        "version": (None, why),
    }


def test_a_wordpress_on_the_host_is_not_detected():
    units = [_unit("apache2.service"), _unit("php8.3-fpm.service"), _unit("mariadb.service")]
    assert _found(_block(units=units)) == {}


@pytest.mark.parametrize(
    "image",
    [
        "bitnami/wordpress:6",
        "bitnami/wordpress-nginx:6",
        "wordpress/wordpress:1",
        "ghcr.io/someone/wordpress:1",
        "wordpressdb:1",
    ],
)
def test_other_images_are_not_taken_for_wordpress(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"status_code": 200}, "ok", "", "ok"),
        # Error establishing a database connection.
        ({"status_code": 500}, "ok", "", "critical"),
        # Maintenance mode during an update.
        ({"status_code": 503}, "ok", "", "critical"),
        ({"status_code": 404}, "ok", "", "critical"),
        ({}, "error", "connection refused", "critical"),
        ({}, "error", "timed out after 10s", "critical"),
        # A plugin closes the REST API to guests: the access brake, not an outage.
        ({}, "denied", "HTTP 401", "warning"),
        # A redirect to HTTPS or the site's own name: the agent does not follow it.
        ({}, "not_allowed", "a redirect to another target", "unknown"),
    ],
)
def test_the_rest_check_is_critical_on_any_other_answer(values, status, error, want):
    assert _status("rest", values, status, error) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"state": "running", "health": "none", "restarts": 0}, "ok"),
        ({"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        # A HEALTHCHECK the compose file adds.
        ({"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ({"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ({"state": "restarting", "health": "none", "restarts": 4}, "critical"),
    ],
)
def test_the_container_rules(values, want):
    assert _status("container", values) == want


def test_the_version_is_read_from_the_container_once_an_hour():
    check = CHECKS["version"]
    assert (check.sensor, check.params) == ("app", {"view": "wordpress_version"})
    assert (check.fields, check.rules) == (["version"], [])
    assert (check.interval, check.test_object) == (3600, False)
    assert _target("version", _block(COMPOSE), "blog") == {
        "kind": "container",
        "name": "blog-wordpress-1",
        "port_hint": None,
        "scheme": None,
    }


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        ({"version": "6.8.3"}, "ok", "", "ok"),
        ({"version": "6.9-RC1"}, "ok", "", "ok"),
        # A version.php the view does not take, or a container that stopped.
        ({}, "error", "container blog-wordpress-1: it holds no version.php", "critical"),
        # An agent without the app sensor, or one on another system than Linux.
        ({}, "unsupported", "unknown sensor app", "unknown"),
    ],
)
def test_the_version_is_shown_and_not_rated(values, status, error, want):
    assert _status("version", values, status, error) == want


def test_the_card_shows_the_container_the_rest_api_and_the_version():
    assert [(i.check_key, i.field, i.label) for i in MODULE.card] == [
        ("container", "state", "Container"),
        ("container", "health", "Container health"),
        ("rest", "status_code", "REST API"),
        ("version", "version", "Version"),
    ]
