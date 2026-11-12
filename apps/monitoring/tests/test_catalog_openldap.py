# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module openldap (R-1242): the image osixia/openldap gets the container check
and an LDAP WhoAmI on 389; the package's slapd.service gets the unit check, the same WhoAmI
and the certificate behind StartTLS on 389 once an hour; any LDAP answer counts, busy or
unavailable is critical; the certificate warns below 22 days and is critical below 9; the
pre-releases on 3890, phpLDAPadmin and other LDAP servers are not bound or not taken."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["openldap"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
IMAGE = "osixia/openldap:1.5.0"
UNIT = "slapd.service"


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


def _container(name, image=IMAGE, project="", service="", ports=(389, 636)):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": "none",
        "ports": [{"private": p, "public": p, "proto": "tcp"} for p in ports],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


# slapd with phpLDAPadmin in one compose project.
COMPOSE = [
    _container("ldap-openldap-1", project="ldap", service="openldap"),
    _container("ldap-admin-1", "osixia/phpldapadmin:0.9.0", "ldap", "admin", (80, 443)),
]


def _found(block):
    return {
        key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "openldap"
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
        block, key = _block(COMPOSE), "ldap"
    else:
        block, key = _block(units=[_unit(UNIT)]), "openldap"
    config, why = probe_config(
        MODULE, CHECKS[check_key], key, _found(block)[key], block["containers"]
    )
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert list(CHECKS) == ["container", "answers", "service", "service_answers", "certificate"]
    assert MODULE.detect.container_images == ["osixia/openldap"]
    assert MODULE.detect.units == [UNIT]
    assert all(c.credential is None for c in MODULE.checks)


def test_both_protocol_checks_ask_ldap_on_389_without_tls():
    for key in ("answers", "service_answers"):
        check = CHECKS[key]
        assert check.sensor == "proto"
        assert check.params == {"protocol": "ldap", "starttls": False, "status_path": ""}
        assert (check.target.port_hint, check.target.scheme) == (389, None)
        assert check.fields == ["ok", "detail", "duration_ms"]
        assert (check.interval, check.test_object) == (300, False)


def test_only_the_package_gets_the_certificate_behind_starttls_once_an_hour():
    # The image asks for a client certificate in TLS by default (LDAP_TLS_VERIFY_CLIENT).
    assert [c.key for c in MODULE.checks if c.sensor == "tls"] == ["certificate"]
    check = CHECKS["certificate"]
    assert (check.target.kind, check.target.port_hint) == ("unit", 389)
    assert check.params == {"server_name": "", "starttls": "ldap"}
    assert check.fields == ["days_left", "not_after", "issuer", "chain_ok"]
    assert (check.interval, check.test_object) == (3600, False)


def test_slapd_in_its_project_gets_its_container_and_389():
    block = _block(COMPOSE)
    assert _found(block) == {
        "ldap": {"services": {"admin": "osixia/phpldapadmin", "openldap": "osixia/openldap"}}
    }
    assert _bind(block, "ldap") == {
        "container": ("ldap-openldap-1", None),
        "answers": ("ldap-openldap-1", None),
        "service": (None, "no unit for this instance"),
        "service_answers": (None, "no unit for this instance"),
        "certificate": (None, "no unit for this instance"),
    }
    assert _target("answers", block, "ldap") == {
        "kind": "container",
        "name": "ldap-openldap-1",
        "port_hint": 389,
        "scheme": None,
    }


@pytest.mark.parametrize(
    "image",
    [
        "osixia/openldap:1.4.0",
        "docker.io/osixia/openldap:latest",
        "osixia/openldap@sha256:" + "f" * 64,
    ],
)
def test_the_image_started_without_compose_gets_the_container_and_389(image):
    block = _block([_container("openldap", image)])
    bound = _bind(block, "openldap")
    assert (bound["container"], bound["answers"]) == (("openldap", None), ("openldap", None))


def test_a_pre_release_on_3890_gets_no_protocol_check():
    block = _block([_container("openldap", "osixia/openldap:2.6.15-rc1", ports=(3890, 6360))])
    bound = _bind(block, "openldap")
    assert bound["container"] == ("openldap", None)
    assert bound["answers"] == (None, "container openldap has no port 389")


def test_the_package_gets_its_unit_389_and_the_certificate():
    block = _block(units=[_unit(UNIT), _unit("nginx.service")])
    assert _found(block) == {"openldap": {"matched_by": [f"unit:{UNIT}"]}}
    assert _bind(block, "openldap") == {
        "container": (None, "no container for this instance"),
        "answers": (None, "no container for this instance"),
        "service": (UNIT, None),
        "service_answers": (UNIT, None),
        "certificate": (UNIT, None),
    }
    for key in ("service_answers", "certificate"):
        assert _target(key, block, "openldap") == {
            "kind": "unit",
            "name": UNIT,
            "port_hint": 389,
            "scheme": None,
        }


@pytest.mark.parametrize(
    "image",
    [
        "bitnami/openldap:2.6",
        "bitnamilegacy/openldap:2.6.10",
        "osixia/phpldapadmin:0.9.0",
        "389ds/dirsrv:3.1",
        "ghcr.io/someone/openldap:1",
    ],
)
def test_other_images_are_not_taken_for_openldap(image):
    assert _found(_block([_container("x", image, "x", "x")])) == {}


def test_the_389_directory_server_is_not_openldap():
    assert _found(_block(units=[_unit("dirsrv@example.service")])) == {}


def _answers(ok, detail):
    return {"ok": ok, "detail": detail, "duration_ms": 3}


@pytest.mark.parametrize("check_key", ["answers", "service_answers"])
@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        (_answers(True, "ldap"), "ok", "", "ok"),
        # The access rules refuse the anonymous operation: slapd answered.
        (_answers(True, "ldap: result 13"), "ok", "", "ok"),
        (_answers(False, "ldap: busy"), "ok", "", "critical"),
        (_answers(False, "ldap: unavailable"), "ok", "", "critical"),
        ({}, "error", "connection refused", "critical"),
    ],
)
def test_the_protocol_check_is_critical_unless_slapd_answers(
    check_key, values, status, error, want
):
    assert _status(check_key, values, status, error) == want


def _cert(days_left):
    return {
        "days_left": days_left,
        "not_after": "2020-03-01T00:00:00Z",
        "issuer": "CN=Example CA",
        "chain_ok": True,
    }


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        (_cert(60), "ok", "", "ok"),
        (_cert(22), "ok", "", "ok"),
        (_cert(21), "ok", "", "warning"),
        (_cert(9), "ok", "", "warning"),
        (_cert(8), "ok", "", "critical"),
        (_cert(-3), "ok", "", "critical"),
        # A slapd without TLS refuses StartTLS.
        ({}, "error", "ldap: StartTLS refused (result 2)", "critical"),
        ({}, "error", "tls: handshake failure", "critical"),
    ],
)
def test_the_certificate_warns_below_22_days_and_is_critical_below_9(values, status, error, want):
    assert _status("certificate", values, status, error) == want


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("container", {"state": "running", "health": "none", "restarts": 0}, "ok"),
        ("container", {"state": "running", "health": "unhealthy", "restarts": 0}, "critical"),
        ("container", {"state": "exited", "health": "none", "restarts": 1}, "critical"),
        ("service", {"active_state": "active", "sub_state": "running"}, "ok"),
        # The unit the init script gives: running while slapd lives, exited once it died.
        ("service", {"active_state": "active", "sub_state": "exited"}, "critical"),
        ("service", {"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_the_container_and_unit_rules(check_key, values, want):
    assert _status(check_key, values) == want


def test_the_card_shows_the_container_or_the_service_ldap_and_the_certificate():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("container", "state"),
        ("container", "health"),
        ("answers", "detail"),
        ("service", "active_state"),
        ("service_answers", "detail"),
        ("certificate", "days_left"),
    ]
