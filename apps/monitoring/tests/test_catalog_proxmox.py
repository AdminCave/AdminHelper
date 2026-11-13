# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules proxmox-ve, proxmox-backup, ceph and sanoid (R-1230): their unit or
marker finds them, each check asks its view, and each rule fires at its threshold and not
without it."""

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
    "proxmox-ve": "pvescheduler.service",
    "proxmox-backup": "proxmox-backup-proxy.service",
    "ceph": "ceph-mon@pve1.service",
}
MODULES = (*UNITS, "sanoid")


def _inventory(units=(), markers=None, state="running"):
    return clean_inventory(
        {
            "ts": T0,
            "duration_ms": 900,
            "partial": False,
            "units": [{"name": u, "state": state} for u in units],
            "sockets": [],
            "containers": [],
            "markers": markers or {},
            "ports": [],
        }
    )


def _seen(inv):
    return sorted(m for m, _ in match_inventory(inv, CATALOG) if m in MODULES)


def _check(module_id, check_key):
    return next(c for c in CATALOG.modules[module_id].checks if c.key == check_key)


def _status(module_id, check_key, **values):
    """The status the probe checker gives a result of the module's check with these values."""
    module = CATALOG.modules[module_id]
    key = UNITS.get(module_id, module_id)
    config, why = probe_config(module, _check(module_id, check_key), key, {}, [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_modules_load_through_the_loader():
    assert CATALOG.errors == ()
    for module_id in MODULES:
        assert module_id in CATALOG.modules


@pytest.mark.parametrize("module_id", sorted(UNITS))
def test_each_unit_finds_its_module_alone(module_id):
    assert _seen(_inventory([UNITS[module_id]])) == [module_id]


def test_neither_the_daemon_nor_an_osd_finds_a_module():
    # pvedaemon runs on a node whose scheduler may be stopped; an OSD host has many OSD units,
    # each of which would repeat the cluster-wide check of its monitor.
    assert (
        _seen(_inventory(["pvedaemon.service", "ceph-osd@0.service", "ceph-osd@1.service"])) == []
    )


def test_a_stopped_unit_finds_nothing():
    assert _seen(_inventory(UNITS.values(), state="inactive")) == []


def test_a_proxmox_host_with_backup_ceph_and_sanoid_has_all_four():
    inv = _inventory(UNITS.values(), markers={"sanoid.bin": True})
    assert _seen(inv) == sorted(MODULES)


@pytest.mark.parametrize(
    ("module_id", "check_key", "view", "interval", "timeout_s"),
    [
        ("proxmox-ve", "cluster", "pve_cluster", 300, 30),
        ("proxmox-ve", "backup", "pve_jobs", 900, 20),
        ("proxmox-ve", "updates", "pve_updates", 86400, 20),
        ("proxmox-backup", "datastores", "pbs_status", 900, 30),
        ("ceph", "health", "ceph_health", 300, 20),
    ],
)
def test_each_app_check_asks_its_view_of_the_unit(module_id, check_key, view, interval, timeout_s):
    check = _check(module_id, check_key)
    assert (check.interval, check.timeout_s) == (interval, timeout_s)
    config, why = probe_config(CATALOG.modules[module_id], check, UNITS[module_id], {}, [])
    assert why is None, why
    assert config["params"] == {"view": view}
    assert (config["target"]["kind"], config["target"]["name"]) == ("unit", UNITS[module_id])


def test_the_sanoid_marker_makes_one_instance_and_its_host_check_binds():
    module = CATALOG.modules["sanoid"]
    assert module.detect.markers[0].paths == ["/usr/sbin/sanoid"]
    assert module.detect.markers[0].packages == ["sanoid"]
    seen = match_inventory(_inventory(markers={"sanoid.bin": True}), CATALOG)
    assert seen[("sanoid", "sanoid")] == {"matched_by": ["marker:sanoid.bin"]}
    check = _check("sanoid", "snapshots")
    assert (check.sensor, check.params, check.target, check.interval) == (
        "host",
        {"view": "zfs_snapshots"},
        None,
        3600,
    )
    config, why = probe_config(module, check, "sanoid", seen[("sanoid", "sanoid")], [])
    assert why is None, why


@pytest.mark.parametrize("present", [None, False])
def test_without_the_marker_there_is_no_sanoid(present):
    markers = {} if present is None else {"sanoid.bin": present}
    assert _seen(_inventory(markers=markers)) == []


@pytest.mark.parametrize("module_id", sorted(UNITS))
@pytest.mark.parametrize(("state", "want"), [("active", "ok"), ("inactive", "critical")])
def test_a_unit_that_is_not_active_is_critical(module_id, state, want):
    assert _status(module_id, "service", active_state=state, sub_state="dead") == want


CLUSTER_OK = {"quorate": True, "nodes_offline": 0, "ha_error": 0, "replication_failed": 0}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"quorate": False}, "critical"),
        ({"ha_error": 1}, "critical"),
        ({"nodes_offline": 1}, "warning"),
        ({"replication_failed": 1}, "warning"),
        ({"nodes_offline": 1, "ha_error": 1}, "critical"),
    ],
)
def test_each_pve_cluster_rule_fires(change, want):
    assert _status("proxmox-ve", "cluster", **{**CLUSTER_OK, **change}) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"jobs": 2, "jobs_failed": 0, "last_run_age_s": 86400 * 30}, "ok"),
        ({"jobs": 0, "jobs_failed": 0}, "ok"),
        ({"jobs": 2, "jobs_failed": 1, "last_run_age_s": 60}, "warning"),
        ({"jobs": 2, "jobs_failed": 2, "last_run_age_s": 60}, "critical"),
    ],
)
def test_the_backup_runs_rate_failures_in_a_row_and_not_their_age(values, want):
    assert _status("proxmox-ve", "backup", **values) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"updates": 0, "subscription_active": False}, "ok"),
        ({"updates": 3, "subscription_active": True}, "warning"),
    ],
)
def test_pending_updates_warn_and_the_subscription_does_not(values, want):
    assert _status("proxmox-ve", "updates", **values) == want


PBS_OK = {"datastores": 2, "maintenance": 0, "tasks_failed": 0, "max_used_pct": 50.0}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"min_full_days": 0}, "ok"),
        ({"max_used_pct": 79.9}, "ok"),
        ({"max_used_pct": 80.0}, "warning"),
        ({"max_used_pct": 90.0}, "critical"),
        ({"maintenance": 1}, "warning"),
        ({"tasks_failed": 1}, "critical"),
    ],
)
def test_each_pbs_rule_fires_at_its_threshold(change, want):
    assert _status("proxmox-backup", "datastores", **{**PBS_OK, **change}) == want


def test_a_pbs_without_a_used_datastore_is_unknown_until_one_fires():
    # No use to rate: the check stays unknown, but a failed job still rates it.
    empty = {"datastores": 0, "maintenance": 0, "tasks_failed": 0}
    assert _status("proxmox-backup", "datastores", **empty) == "unknown"
    assert _status("proxmox-backup", "datastores", **{**empty, "tasks_failed": 1}) == "critical"


CEPH_OK = {"health": "HEALTH_OK", "checks": 0, "raw_used_pct": 40.0, "max_pool_used_pct": 50.0}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"raw_used_pct": 95.0}, "ok"),
        ({"health": "HEALTH_WARN", "checks": 2}, "warning"),
        ({"health": "HEALTH_ERR", "checks": 1}, "critical"),
        ({"max_pool_used_pct": 74.9}, "ok"),
        ({"max_pool_used_pct": 75.0}, "warning"),
        ({"max_pool_used_pct": 85.0}, "critical"),
    ],
)
def test_each_ceph_rule_fires_at_its_threshold(change, want):
    assert _status("ceph", "health", **{**CEPH_OK, **change}) == want


@pytest.mark.parametrize(
    ("status", "want"), [("ok", "ok"), ("warning", "warning"), ("critical", "critical")]
)
def test_sanoid_rates_as_sanoid_does(status, want):
    assert _status("sanoid", "snapshots", status=status) == want
