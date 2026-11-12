# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module opnsense (R-1248): the marker finds the firewall, every check binds
to the instance, and each rule fires at its threshold and not just below it."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["opnsense"]
# Far from the test machine's clock, so only the report's own time makes a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"


def _block(markers):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": [],
        "sockets": [],
        "containers": [],
        "markers": markers,
        "ports": [],
    }


def _status(check_key, **values):
    """The status the probe checker gives a result of the check with these values."""
    check = next(c for c in MODULE.checks if c.key == check_key)
    config, why = probe_config(MODULE, check, "opnsense", {}, [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_through_the_loader():
    assert CATALOG.errors == ()
    assert [c.key for c in MODULE.checks] == ["services", "gateways", "firmware", "states", "carp"]
    assert {c.key: c.interval for c in MODULE.checks}["firmware"] == 3600
    assert all(c.sensor == "opnsense" and c.target is None for c in MODULE.checks)


def test_the_marker_makes_the_instance_opnsense_and_every_check_binds():
    seen = match_inventory(_block({"opnsense.core": True}), CATALOG)
    assert seen[("opnsense", "opnsense")] == {"matched_by": ["marker:opnsense.core"]}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, "opnsense", seen[("opnsense", "opnsense")], [])
        assert why is None, (check.key, why)
        assert config["params"] == {"view": check.key}


@pytest.mark.parametrize("markers", [{}, {"opnsense.core": False}])
def test_without_the_marker_there_is_no_firewall(markers):
    assert not any(module == "opnsense" for module, _ in match_inventory(_block(markers), CATALOG))


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("services", {"stopped": 1}, "critical"),
        ("services", {"stopped": 0}, "ok"),
        ("gateways", {"down": 1, "degraded": 0}, "critical"),
        ("gateways", {"down": 0, "degraded": 1}, "warning"),
        ("gateways", {"down": 0, "degraded": 0, "forced_down": 2}, "ok"),
        ("states", {"used_pct": 80.0}, "warning"),
        ("states", {"used_pct": 79.9}, "ok"),
        ("states", {"used_pct": 95.0}, "critical"),
        ("states", {"used_pct": 94.9}, "warning"),
        ("carp", {"init": 1, "demotion": 0}, "critical"),
        ("carp", {"init": 0, "demotion": 240}, "warning"),
        ("carp", {"init": 0, "demotion": 0, "maintenance": True}, "ok"),
        ("firmware", {"version": "26.7.1", "update_available": True, "update_reboot": True}, "ok"),
    ],
)
def test_each_rule_fires_at_its_threshold(check_key, values, want):
    assert _status(check_key, **values) == want


def test_the_card_shows_version_update_services_gateways_states_and_carp():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("firmware", "version"),
        ("firmware", "update_available"),
        ("services", "stopped"),
        ("gateways", "down"),
        ("states", "used_pct"),
        ("carp", "master"),
    ]
