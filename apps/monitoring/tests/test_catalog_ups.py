# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules nut, nut-monitor and apcupsd (R-1229): their units find them, the UPS
checks bind to the unit, and each rule fires on its state and not without it."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import clean_inventory, match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
# Far from the test machine's clock, so only the report's own time makes a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"

UNITS = {
    "nut": "nut-server.service",
    "nut-monitor": "nut-monitor.service",
    "apcupsd": "apcupsd.service",
}


def _inventory(*units, state="running"):
    return clean_inventory(
        {
            "ts": T0,
            "duration_ms": 900,
            "partial": False,
            "units": [{"name": u, "state": state} for u in units],
            "sockets": [],
            "containers": [],
            "markers": {},
            "ports": [],
        }
    )


def _seen(inv):
    return sorted(m for m, _ in match_inventory(inv, CATALOG) if m in UNITS)


def _status(module_id, check_key, **values):
    """The status the probe checker gives a result of the module's check with these values."""
    module = CATALOG.modules[module_id]
    check = next(c for c in module.checks if c.key == check_key)
    config, why = probe_config(module, check, UNITS[module_id], {}, [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_modules_load_through_the_loader():
    assert CATALOG.errors == ()
    for module_id in UNITS:
        assert module_id in CATALOG.modules


@pytest.mark.parametrize("module_id", sorted(UNITS))
def test_each_unit_finds_its_module_alone(module_id):
    assert _seen(_inventory(UNITS[module_id])) == [module_id]


def test_a_standalone_nut_host_has_both_nut_modules():
    assert _seen(_inventory("nut-server.service", "nut-monitor.service")) == ["nut", "nut-monitor"]


def test_a_stopped_unit_finds_nothing():
    assert _seen(_inventory(*UNITS.values(), state="inactive")) == []


@pytest.mark.parametrize(("module_id", "view"), [("nut", "nut_ups"), ("apcupsd", "apcupsd")])
def test_the_ups_check_asks_its_view_of_the_unit(module_id, view):
    module = CATALOG.modules[module_id]
    check = next(c for c in module.checks if c.key == "ups")
    config, why = probe_config(module, check, UNITS[module_id], {}, [])
    assert why is None, why
    assert config["params"] == {"view": view}
    assert config["target"]["kind"] == "unit"
    assert config["target"]["name"] == UNITS[module_id]


def test_the_nut_check_has_room_for_a_call_per_ups():
    check = next(c for c in CATALOG.modules["nut"].checks if c.key == "ups")
    assert (check.interval, check.timeout_s) == (300, 30)


@pytest.mark.parametrize("module_id", sorted(UNITS))
@pytest.mark.parametrize(("state", "want"), [("active", "ok"), ("inactive", "critical")])
def test_a_unit_that_is_not_active_is_critical(module_id, state, want):
    assert _status(module_id, "service", active_state=state, sub_state="dead") == want


NUT_OK = {
    "ups": 1,
    "on_battery": 0,
    "low_battery": 0,
    "fsd": 0,
    "overload": 0,
    "replace_battery": 0,
    "stale": 0,
    "min_runtime_s": 600,
    "min_charge_pct": 100.0,
}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"min_runtime_s": 60, "min_charge_pct": 5.0}, "ok"),
        ({"on_battery": 1}, "warning"),
        ({"replace_battery": 1}, "warning"),
        ({"low_battery": 1}, "critical"),
        ({"fsd": 1}, "critical"),
        ({"overload": 1}, "critical"),
        ({"stale": 1}, "critical"),
        ({"on_battery": 1, "low_battery": 1}, "critical"),
    ],
)
def test_each_nut_rule_fires_at_its_threshold(change, want):
    assert _status("nut", "ups", **{**NUT_OK, **change}) == want


def test_a_nut_ups_without_runtime_or_charge_is_ok():
    values = {k: v for k, v in NUT_OK.items() if k not in ("min_runtime_s", "min_charge_pct")}
    assert _status("nut", "ups", **values) == "ok"


APC_OK = {
    "online": True,
    "on_battery": False,
    "low_battery": False,
    "commlost": False,
    "charge_pct": 100.0,
    "runtime_s": 2700,
    "transfers": 0,
}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"transfers": 12, "charge_pct": 20.0, "runtime_s": 60}, "ok"),
        ({"online": False, "on_battery": True}, "warning"),
        ({"online": False, "on_battery": True, "low_battery": True}, "critical"),
        ({"online": False, "commlost": True}, "critical"),
    ],
)
def test_each_apcupsd_rule_fires(change, want):
    assert _status("apcupsd", "ups", **{**APC_OK, **change}) == want
