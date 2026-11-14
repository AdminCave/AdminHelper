# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module collabora (R-1242): the image collabora/code gets the container check
and coolwsd's port 9980 asked in the protocol found there; the package's coolwsd.service gets
the unit check and the same on 9980; an answer that is no HTTP in plain or in TLS is as
critical as a refused port; the images of Nextcloud AIO and the Helm chart's name are not
Collabora's image."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["collabora"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "collabora/code:25.04.10.3.1"
UNIT = "coolwsd.service"


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


def _container(name, image=IMAGE, project="", service="", ports=((9980, "tcp"),)):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        # The 25.04 images have no HEALTHCHECK.
        "health": "none",
        "ports": [{"private": p, "public": p, "proto": proto} for p, proto in ports],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


# Collabora next to Nextcloud in one compose project.
COMPOSE = [
    _container("nextcloud-app-1", "nextcloud:31-apache", "nextcloud", "app", [(80, "tcp")]),
    _container("nextcloud-db-1", "mariadb:11.4", "nextcloud", "db", [(3306, "tcp")]),
    _container("nextcloud-collabora-1", project="nextcloud", service="collabora"),
]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "collabora"
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
        block, key = _block(COMPOSE), "nextcloud"
    else:
        block, key = _block(units=[_unit(UNIT)]), "collabora"
    config, why = probe_config(
        MODULE, CHECKS[check_key], key, _found(block)[key], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "answers", "service", "service_answers"]
    assert MODULE.detect.units == [UNIT]
    assert all(c.credential is None for c in MODULE.checks)


def test_both_port_checks_find_the_protocol_themselves():
    # ssl.enable decides whether coolwsd speaks TLS on 9980; no scheme is fixed.
    for key in ("answers", "service_answers"):
        check = CHECKS[key]
        assert check.sensor == "proto"
        assert check.params == {"protocol": "auto", "starttls": False, "status_path": ""}
        assert (check.target.port_hint, check.target.scheme) == (9980, None)
        assert check.fields == ["ok", "detail", "tls_ok", "duration_ms"]
        assert (check.interval, check.test_object) == (300, False)


def test_collabora_in_the_nextcloud_project_gets_its_container_and_9980():
    block = _block(COMPOSE)
    assert _found(block) == {
        "nextcloud": {
            "services": {
                "app": "nextcloud",
                "collabora": "collabora/code",
                "db": "mariadb",
            },
            "containers": {
                "app": "nextcloud-app-1",
                "collabora": "nextcloud-collabora-1",
                "db": "nextcloud-db-1",
            },
        }
    }
    assert _bind(block, "nextcloud") == {
        "container": ("nextcloud-collabora-1", None),
        "answers": ("nextcloud-collabora-1", None),
        "service": (None, "no unit for this instance"),
        "service_answers": (None, "no unit for this instance"),
    }
    assert _target("answers", block, "nextcloud") == {
        "kind": "container",
        "name": "nextcloud-collabora-1",
        "port_hint": 9980,
        "scheme": None,
    }


@pytest.mark.parametrize(
    "image",
    [
        "collabora/code:26.04.2.4.1",
        "docker.io/collabora/code:latest",
        "collabora/code@sha256:" + "d" * 64,
    ],
)
def test_the_image_started_without_compose_gets_the_container_and_9980(image):
    block = _block([_container("collabora", image)])
    bound = _bind(block, "collabora")
    assert (bound["container"], bound["answers"]) == (("collabora", None), ("collabora", None))


def test_the_package_gets_its_unit_and_9980():
    block = _block(units=[_unit(UNIT), _unit("nginx.service"), _unit("apache2.service")])
    assert _found(block) == {"collabora": {"matched_by": [f"unit:{UNIT}"]}}
    assert _bind(block, "collabora") == {
        "container": (None, "no container for this instance"),
        "answers": (None, "no container for this instance"),
        "service": (UNIT, None),
        "service_answers": (UNIT, None),
    }
    assert _target("service_answers", block, "collabora") == {
        "kind": "unit",
        "name": UNIT,
        "port_hint": 9980,
        "scheme": None,
    }


@pytest.mark.parametrize(
    "image",
    [
        "nextcloud/aio-collabora:latest",
        "collabora/collabora-online:25.04",
        "ghcr.io/someone/code:1",
        "libreoffice/online:master",
    ],
)
def test_other_images_are_not_taken_for_collabora(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


def _answers(ok, detail, tls_ok=False):
    return {"ok": ok, "detail": detail, "tls_ok": tls_ok, "duration_ms": 12}


@pytest.mark.parametrize("check_key", ["answers", "service_answers"])
@pytest.mark.parametrize(
    ("values", "want"),
    [
        # ssl.enable false (TLS ends at the proxy) and true.
        (_answers(True, "http"), "ok"),
        (_answers(True, "https", tls_ok=True), "ok"),
        (_answers(False, "http: status 503"), "critical"),
        (_answers(False, "closed"), "critical"),
        # coolwsd accepts and answers neither in plain HTTP nor in TLS.
        (_answers(True, "unknown"), "critical"),
        (_answers(True, "tls", tls_ok=True), "critical"),
    ],
)
def test_the_port_check_is_critical_unless_coolwsd_answers_http(check_key, values, want):
    assert _status(check_key, values) == want


def test_a_refused_port_fails_the_check():
    assert _status("answers", {}, "error", "connection refused") == "critical"


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("container", {"state": "running", "health": "none", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "healthy", "restarts": 0}, "ok"),
        # From 26.04: coolwsd --probe found /livez failing.
        ("container", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ("container", {"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ("service", {"active_state": "active", "sub_state": "running"}, "ok"),
        ("service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_the_container_or_the_service_and_the_protocol():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("container", "health"),
        ("answers", "detail"),
        ("service", "active_state"),
        ("service_answers", "detail"),
    ]
