# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module 3cx (R-1241): each running or failed unit of the package 3cxpbx is
an instance of its own with the unit check, an inactive one is none; a stopped service
is critical."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["3cx"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
# The services 3CXStartServices enables (3cxpbx.conf of 3cxpbx 20.0.10) and the firewall.
UNITS = [
    "3CXEventNotificationManager.service",
    "3CXCfgServ01.service",
    "3CXMediaServer.service",
    "3CXPhoneSystemMC01.service",
    "3CXPhoneSystem01.service",
    "3CXIVR01.service",
    "3CXQueueManager01.service",
    "3CXCallFlow01.service",
    "3CXSystemService01.service",
    "3CXAudioProvider01.service",
    "3CXHotelModule01.service",
    "3CXAI.service",
    "3CXGatewayService.service",
    "3CXFirewall.service",
]


def _block(units=()):
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


def _unit(name, state="active", sub="running"):
    return {"name": name, "state": state, "sub": sub}


def _found(block):
    return {key: s for (mid, key), s in match_inventory(block, CATALOG).items() if mid == "3cx"}


def _status(values):
    unit = "3CXPhoneSystem01.service"
    block = _block([_unit(unit)])
    config, why = probe_config(MODULE, CHECKS["service"], unit, _found(block)[unit], [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_the_units_of_the_package():
    assert CATALOG.errors == ()
    assert sorted(MODULE.detect.units) == sorted(UNITS)
    assert list(CHECKS) == ["service"]
    assert CHECKS["service"].sensor == "unit"
    assert CHECKS["service"].fields == ["active_state", "sub_state"]


def test_each_unit_of_a_running_install_is_an_instance_with_the_unit_check():
    block = _block(
        [_unit(u) for u in UNITS if u != "3CXFirewall.service"]
        + [_unit("3CXFirewall.service", sub="exited"), _unit("nginx.service")]
    )
    found = _found(block)
    assert found == {u: {"unit": u} for u in UNITS}
    for unit, summary in found.items():
        config, why = probe_config(MODULE, CHECKS["service"], unit, summary, [])
        assert why is None, why
        assert config["target"] == {"kind": "unit", "name": unit, "port_hint": None, "scheme": None}


def test_an_inactive_unit_is_no_instance_and_a_failed_one_stays():
    block = _block(
        [
            _unit("3CXPhoneSystem01.service"),
            _unit("3CXHotelModule01.service", "inactive", "dead"),
            _unit("3CXAI.service", "failed", "failed"),
        ]
    )
    assert sorted(_found(block)) == ["3CXAI.service", "3CXPhoneSystem01.service"]


@pytest.mark.parametrize("unit", ["3cxpbx.service", "3CXPhoneSystem02.service", "nginx.service"])
def test_other_units_are_not_taken_for_3cx(unit):
    assert _found(_block([_unit(unit)])) == {}


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"active_state": "active", "sub_state": "running"}, "ok"),
        # 3CXFirewall is a oneshot unit that stays active after it ran.
        ({"active_state": "active", "sub_state": "exited"}, "ok"),
        ({"active_state": "activating", "sub_state": "auto-restart"}, "critical"),
        ({"active_state": "failed", "sub_state": "failed"}, "critical"),
        ({"active_state": "inactive", "sub_state": "dead"}, "critical"),
    ],
)
def test_a_unit_that_is_not_active_is_critical(values, want):
    assert _status(values) == want


def test_the_card_shows_the_units_state():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("service", "active_state"),
        ("service", "sub_state"),
    ]
