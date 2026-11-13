# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules mdadm, lvm-thin, hwraid and ipmi (R-1228): a marker finds each one,
its check binds to the instance without a target, and each rule fires at its threshold and
not just below it."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
# Far from the test machine's clock, so only the report's own time makes a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"

MODULES = {
    "mdadm": ("mdadm.md", "mdadm"),
    "lvm-thin": ("lvm-thin.lvs", "lvm_thin"),
    "hwraid": ("hwraid.cli", "raid_ctrl"),
    "ipmi": ("ipmi.device", "ipmi_sensors"),
}


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


def _status(module_id, **values):
    """The status the probe checker gives a result of the module's check with these values."""
    module = CATALOG.modules[module_id]
    config, why = probe_config(module, module.checks[0], module_id, {}, [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_modules_load_with_one_host_check_each():
    assert CATALOG.errors == ()
    for module_id, (_, view) in MODULES.items():
        checks = CATALOG.modules[module_id].checks
        assert [(c.sensor, c.params, c.target) for c in checks] == [("host", {"view": view}, None)]


def test_the_slow_views_run_every_15_minutes_within_the_longest_timeout():
    timing = {
        m: (CATALOG.modules[m].checks[0].interval, CATALOG.modules[m].checks[0].timeout_s)
        for m in MODULES
    }
    assert timing == {
        "mdadm": (300, 10),
        "lvm-thin": (300, 30),
        "hwraid": (900, 30),
        "ipmi": (900, 30),
    }


def test_the_markers_are_the_paths_the_agent_reads():
    paths = {m: CATALOG.modules[m].detect.markers[0].paths for m in MODULES}
    assert paths["hwraid"] == [
        "/opt/MegaRAID/storcli/storcli64",
        "/opt/MegaRAID/perccli/perccli64",
        "/usr/sbin/ssacli",
    ]
    assert paths["ipmi"] == ["/dev/ipmi0", "/dev/ipmi/0", "/dev/ipmidev/0"]
    assert CATALOG.modules["mdadm"].detect.markers[0].packages == ["mdadm"]
    assert CATALOG.modules["lvm-thin"].detect.markers[0].packages == ["lvm2"]


@pytest.mark.parametrize("module_id", sorted(MODULES))
def test_the_marker_makes_one_instance_and_its_check_binds(module_id):
    marker, view = MODULES[module_id]
    seen = match_inventory(_block({marker: True}), CATALOG)
    assert seen[(module_id, module_id)] == {"matched_by": [f"marker:{marker}"]}
    module = CATALOG.modules[module_id]
    config, why = probe_config(
        module, module.checks[0], module_id, seen[(module_id, module_id)], []
    )
    assert why is None, why
    assert config["params"] == {"view": view}


@pytest.mark.parametrize("module_id", sorted(MODULES))
@pytest.mark.parametrize("present", [None, False])
def test_without_the_marker_there_is_no_instance(module_id, present):
    marker, _ = MODULES[module_id]
    markers = {} if present is None else {marker: present}
    assert not any(m == module_id for m, _ in match_inventory(_block(markers), CATALOG))


@pytest.mark.parametrize(
    ("module_id", "values", "want"),
    [
        ("mdadm", {"arrays": 2, "degraded": 0, "faulty_devices": 0, "mismatch_cnt": 128}, "ok"),
        ("mdadm", {"degraded": 1, "faulty_devices": 0}, "critical"),
        ("mdadm", {"degraded": 0, "faulty_devices": 1}, "critical"),
        ("mdadm", {"degraded": 0, "faulty_devices": 0, "resyncing": 1}, "ok"),
        ("lvm-thin", {"max_data_pct": 79.9, "max_meta_pct": 0.0, "failed": 0, "busy": False}, "ok"),
        (
            "lvm-thin",
            {"max_data_pct": 80.0, "max_meta_pct": 0.0, "failed": 0, "busy": False},
            "warning",
        ),
        (
            "lvm-thin",
            {"max_data_pct": 89.9, "max_meta_pct": 0.0, "failed": 0, "busy": False},
            "warning",
        ),
        (
            "lvm-thin",
            {"max_data_pct": 90.0, "max_meta_pct": 0.0, "failed": 0, "busy": False},
            "critical",
        ),
        ("lvm-thin", {"max_data_pct": 0.0, "max_meta_pct": 69.9, "failed": 0, "busy": False}, "ok"),
        (
            "lvm-thin",
            {"max_data_pct": 0.0, "max_meta_pct": 70.0, "failed": 0, "busy": False},
            "warning",
        ),
        (
            "lvm-thin",
            {"max_data_pct": 0.0, "max_meta_pct": 80.0, "failed": 0, "busy": False},
            "critical",
        ),
        (
            "lvm-thin",
            {"max_data_pct": 0.0, "max_meta_pct": 0.0, "failed": 1, "busy": False},
            "critical",
        ),
        ("lvm-thin", {"busy": True}, "warning"),
        ("hwraid", {"ctrl_bad": 0, "vd_not_optimal": 0, "pd_failed": 0, "bbu_bad": 0}, "ok"),
        ("hwraid", {"ctrl_bad": 1, "vd_not_optimal": 0, "pd_failed": 0, "bbu_bad": 0}, "critical"),
        ("hwraid", {"ctrl_bad": 0, "vd_not_optimal": 1, "pd_failed": 0, "bbu_bad": 0}, "critical"),
        ("hwraid", {"ctrl_bad": 0, "vd_not_optimal": 0, "pd_failed": 1, "bbu_bad": 0}, "critical"),
        ("hwraid", {"ctrl_bad": 0, "vd_not_optimal": 0, "pd_failed": 0, "bbu_bad": 1}, "warning"),
        ("ipmi", {"sensors": 40, "critical": 0, "noncritical": 0}, "ok"),
        ("ipmi", {"sensors": 40, "critical": 0, "noncritical": 1}, "warning"),
        ("ipmi", {"sensors": 40, "critical": 1, "noncritical": 1}, "critical"),
    ],
)
def test_each_rule_fires_at_its_threshold(module_id, values, want):
    assert _status(module_id, **values) == want
