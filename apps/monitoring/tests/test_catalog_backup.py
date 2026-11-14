# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules of a backup host (R-1233): urbackup, backuppc, rsnapshot and veeam.
Their unit or marker finds them, each check binds to the unit or runs on the host, and each
rule fires at its threshold and not below it."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.catalog.sensors import field_allowed
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULES = ("urbackup", "backuppc", "rsnapshot", "veeam")
UNITS = {
    "urbackup": "urbackupsrv.service",
    "backuppc": "backuppc.service",
    "veeam": "veeamservice.service",
}
# Far from the test machine's clock, so only the report's own time makes a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
DAY_AND_TWO_HOURS = 26 * 3600


def _block(units=(), markers=None):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": list(units),
        "sockets": [],
        "containers": [],
        "markers": markers or {},
        "ports": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


def _found(block, module_id):
    return {k: s for (m, k), s in match_inventory(block, CATALOG).items() if m == module_id}


def _seen(block):
    return sorted({m for m, _ in match_inventory(block, CATALOG) if m in MODULES})


def _instance(module_id):
    if module_id == "rsnapshot":
        return _block(markers={"rsnapshot.bin": True}), "rsnapshot"
    return _block(units=[_unit(UNITS[module_id])]), UNITS[module_id]


def _config(module_id, check_key):
    block, key = _instance(module_id)
    module = CATALOG.modules[module_id]
    check = next(c for c in module.checks if c.key == check_key)
    config, why = probe_config(module, check, key, _found(block, module_id)[key], [])
    assert why is None, why
    return config


def _result(module_id, check_key, result):
    config = {**_config(module_id, check_key), "_check_id": "chk"}
    report = {"timestamp": STAMP, "probes": {"chk": {"ts": T0, "duration_ms": 40, **result}}}
    return ProbeChecker().evaluate(config, report)[0]


def _status(module_id, check_key, **values):
    return _result(module_id, check_key, {"status": "ok", "values": values, "error": ""})


def test_the_modules_load_through_the_loader():
    assert CATALOG.errors == ()
    for module_id in MODULES:
        assert module_id in CATALOG.modules


@pytest.mark.parametrize(("module_id", "unit"), sorted(UNITS.items()))
def test_each_unit_finds_its_module_alone(module_id, unit):
    assert _seen(_block(units=[_unit(unit)])) == [module_id]


def test_a_stopped_unit_finds_nothing():
    assert _seen(_block(units=[_unit(u, "inactive") for u in UNITS.values()])) == []


def test_the_rsnapshot_marker_makes_one_instance_with_a_host_check():
    module = CATALOG.modules["rsnapshot"]
    assert module.detect.markers[0].paths == ["/usr/bin/rsnapshot"]
    assert module.detect.markers[0].packages == ["rsnapshot"]
    assert _found(*_instance("rsnapshot")) == {
        "rsnapshot": {"matched_by": ["marker:rsnapshot.bin"]}
    }
    config = _config("rsnapshot", "runs")
    assert (config["sensor"], config["params"], config["target"]) == (
        "host",
        {"view": "rsnapshot"},
        None,
    )


@pytest.mark.parametrize("present", [None, False])
def test_without_the_marker_there_is_no_rsnapshot(present):
    markers = {} if present is None else {"rsnapshot.bin": present}
    assert _seen(_block(markers=markers)) == []


@pytest.mark.parametrize(
    ("module_id", "check_key", "view", "interval"),
    [
        ("urbackup", "clients", "urbackup_status", 900),
        ("backuppc", "hosts", "backuppc_status", 900),
        ("veeam", "jobs", "veeam_sessions", 3600),
        ("rsnapshot", "runs", "rsnapshot", 3600),
    ],
)
def test_each_view_runs_at_its_interval(module_id, check_key, view, interval):
    check = next(c for c in CATALOG.modules[module_id].checks if c.key == check_key)
    assert (check.params, check.interval) == ({"view": view}, interval)
    assert _config(module_id, check_key)["params"] == {"view": view}


@pytest.mark.parametrize("module_id", ["backuppc", "veeam"])
def test_the_app_checks_bind_to_the_unit_without_a_credential(module_id):
    config = _config(module_id, "hosts" if module_id == "backuppc" else "jobs")
    assert (config["target"]["kind"], config["target"]["name"]) == ("unit", UNITS[module_id])
    assert config["credential"] is None


def test_urbackup_asks_its_web_port_with_a_stored_web_user():
    config = _config("urbackup", "clients")
    assert config["target"]["name"] == "urbackupsrv.service"
    assert (config["target"]["port_hint"], config["target"]["scheme"]) == (55414, "http")
    assert config["credential"] == {
        "ref": "urbackup/urbackupsrv.service/default",
        "use": "basic",
    }


def test_urbackup_without_a_stored_web_user_warns():
    result = {"status": "no_credential", "values": {}, "error": ""}
    assert _result("urbackup", "clients", result) == "warning"


@pytest.mark.parametrize("module_id", sorted(UNITS))
@pytest.mark.parametrize(("state", "want"), [("active", "ok"), ("inactive", "critical")])
def test_a_unit_that_is_not_active_is_critical(module_id, state, want):
    assert _status(module_id, "service", active_state=state, sub_state="dead") == want


URBACKUP_OK = {
    "clients": 3,
    "clients_file_failed": 0,
    "clients_image_failed": 0,
    "clients_unseen_24h": 1,
    "file_backup_age_max_s": DAY_AND_TWO_HOURS,
    "nospc_fatal": False,
    "database_error": False,
}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"clients_unseen_24h": 3}, "ok"),
        ({"file_backup_age_max_s": DAY_AND_TWO_HOURS + 1}, "warning"),
        ({"clients_file_failed": 1}, "critical"),
        ({"clients_image_failed": 1}, "critical"),
        ({"nospc_fatal": True}, "critical"),
        ({"database_error": True}, "critical"),
    ],
)
def test_each_urbackup_rule_fires(change, want):
    assert _status("urbackup", "clients", **{**URBACKUP_OK, **change}) == want


BACKUPPC_OK = {
    "hosts": 4,
    "hosts_failed": 0,
    "hosts_no_ping": 1,
    "hosts_never_backed_up": 1,
    "jobs_active": 1,
    "backup_age_max_s": DAY_AND_TWO_HOURS,
}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"backup_age_max_s": DAY_AND_TWO_HOURS + 1}, "warning"),
        ({"hosts_failed": 1}, "critical"),
        ({"hosts_failed": 1, "backup_age_max_s": DAY_AND_TWO_HOURS + 1}, "critical"),
    ],
)
def test_each_backuppc_rule_fires(change, want):
    assert _status("backuppc", "hosts", **{**BACKUPPC_OK, **change}) == want


VEEAM_OK = {
    "jobs": 2,
    "jobs_failed": 0,
    "jobs_warning": 0,
    "sessions_running": 1,
    "last_success_age_max_s": DAY_AND_TWO_HOURS,
}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"jobs_warning": 1}, "warning"),
        ({"last_success_age_max_s": DAY_AND_TWO_HOURS + 1}, "warning"),
        ({"jobs_failed": 1}, "critical"),
    ],
)
def test_each_veeam_rule_fires(change, want):
    assert _status("veeam", "jobs", **{**VEEAM_OK, **change}) == want


RSNAPSHOT_OK = {
    "last_status": "ok",
    "running": False,
    "lock_stale": False,
    "last_success_age_s": DAY_AND_TWO_HOURS,
}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"running": True}, "ok"),
        ({"last_status": "warning"}, "warning"),
        ({"last_success_age_s": DAY_AND_TWO_HOURS + 1}, "warning"),
        ({"last_status": "error"}, "critical"),
        ({"lock_stale": True}, "critical"),
    ],
)
def test_each_rsnapshot_rule_fires(change, want):
    assert _status("rsnapshot", "runs", **{**RSNAPSHOT_OK, **change}) == want


@pytest.mark.parametrize("field", ["result", "exec_status", "last_run_age_s"])
def test_the_unit_sensor_returns_the_last_run_of_a_timer_service(field):
    assert field_allowed("unit", field, {})
