# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module unifi-os-server (R-1244): the unit uosserver is the instance and gets the
service, the certificate of port 11443 and the view unifi_network every five minutes with the
key in header X-API-KEY; a gateway offline is critical, a cause offline warns, devices offline
behind a cause, updating devices and firmware updates alone are no problem."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["unifi-os-server"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
UNIT = "uosserver.service"
FIELDS = [
    "sites",
    "devices",
    "offline",
    "offline_root",
    "gateways_offline",
    "updating",
    "firmware_updatable",
    "pending",
    "clients",
]


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


def _block(units):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": list(units),
        "sockets": [],
        "containers": [],
        "markers": {},
        "ports": [],
    }


def _found(block, module="unifi-os-server"):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == module}


def _config(check_key):
    summary = _found(_block([_unit(UNIT)]))[UNIT]
    config, why = probe_config(MODULE, CHECKS[check_key], UNIT, summary, [])
    assert why is None, why
    return config


def _status(check_key, values, status="ok", error=""):
    config = {**_config(check_key), "_check_id": "chk"}
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate(config, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert MODULE.version == 1
    assert list(CHECKS) == ["service", "certificate", "network"]
    assert MODULE.detect.units == ["uosserver.service"]
    assert (MODULE.detect.container_images, MODULE.detect.processes) == ([], [])


def test_the_unit_is_the_instance_and_every_check_binds_to_it():
    assert list(_found(_block([_unit(UNIT)]))) == [UNIT]
    assert _config("service")["target"] == {
        "kind": "unit",
        "name": UNIT,
        "port_hint": None,
        "scheme": None,
    }
    for key in ("certificate", "network"):
        assert _config(key)["target"] == {
            "kind": "unit",
            "name": UNIT,
            "port_hint": 11443,
            "scheme": None,
        }


def test_other_units_make_no_instance():
    block = _block([_unit("unifi.service"), _unit("uosserver-updater.service")])
    assert _found(block) == {}


def test_the_view_takes_the_key_in_its_header_and_runs_every_five_minutes():
    check = CHECKS["network"]
    assert (check.sensor, check.params) == ("app", {"view": "unifi_network"})
    assert check.fields == FIELDS
    assert (check.interval, check.timeout_s, check.test_object) == (300, 30, False)
    config = _config("network")
    assert config["credential"] == {
        "ref": "unifi-os-server/uosserver.service/default",
        "use": "header:X-API-KEY",
    }
    assert _config("service")["credential"] is None
    assert _config("certificate")["credential"] is None


def _net(**over):
    values = dict.fromkeys(FIELDS, 0)
    values.update(sites=1, devices=12, clients=140)
    values.update(over)
    return values


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        (_net(), "ok", "", "ok"),
        (_net(offline=1, offline_root=1), "ok", "", "warning"),
        # Three APs behind a switch that is offline: one cause, one warning.
        (_net(offline=4, offline_root=1), "ok", "", "warning"),
        # Every device offline sits behind another one: no cause of its own.
        (_net(offline=3, offline_root=0), "ok", "", "ok"),
        (_net(offline=1, offline_root=1, gateways_offline=1), "ok", "", "critical"),
        (_net(updating=2, firmware_updatable=5, pending=1), "ok", "", "ok"),
        ({}, "denied", "the UniFi Network application turns the key away", "warning"),
        ({}, "unsupported", "unit uosserver.service does not listen on 11443", "unknown"),
    ],
)
def test_a_gateway_offline_is_critical_and_a_cause_offline_warns(values, status, error, want):
    assert _status("network", values, status, error) == want


@pytest.mark.parametrize(
    ("state", "want"),
    [("active", "ok"), ("inactive", "critical"), ("failed", "critical")],
)
def test_the_service_is_critical_when_it_is_not_active(state, want):
    assert _status("service", {"active_state": state, "sub_state": "dead"}) == want


@pytest.mark.parametrize(("days", "want"), [(400, "ok"), (21, "warning"), (8, "critical")])
def test_the_certificate_warns_three_weeks_ahead(days, want):
    values = {"days_left": days, "not_after": "2030-01-01", "issuer": "UniFi", "chain_ok": False}
    assert _status("certificate", values) == want


def test_the_card_shows_the_service_the_devices_offline_and_the_updates():
    assert [(i.check_key, i.field, i.label) for i in MODULE.card] == [
        ("service", "active_state", "Service"),
        ("network", "offline", "Devices offline"),
        ("network", "firmware_updatable", "Firmware updates"),
    ]
