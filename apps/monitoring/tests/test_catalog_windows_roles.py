# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules of the Windows roles, Windows backups and CUPS (R-1246, R-1436): the
service finds each one, its checks bind to that service, and each rule fires at its threshold
and not just below it. A value the agent leaves out carries no rule but its own (R-1475)."""

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

_SERVICE = ("unit", None)

# module id -> (the unit as the agent lists it, the instance key, {check key: (sensor, view)})
MODULES = {
    "hyperv": ("vmms", "vmms", {"service": _SERVICE, "vms": ("app", "hyperv")}),
    "dfsr": ("DFSR", "DFSR", {"service": _SERVICE, "folders": ("app", "dfsr")}),
    "mssql": (
        "MSSQLSERVER",
        "MSSQLSERVER",
        {"service": _SERVICE, "events": ("app", "mssql_events")},
    ),
    "wsus": ("WsusService", "WsusService", {"service": _SERVICE, "content": ("app", "wsus")}),
    "windows-fileserver": ("LanmanServer", "LanmanServer", {"storage": ("host", "storage")}),
    "print-server": ("Spooler", "Spooler", {"service": _SERVICE, "queues": ("app", "print")}),
    "cups": (
        "cups.service",
        "cups.service",
        {"service": _SERVICE, "queues": ("app", "cups_queues")},
    ),
    "defender": ("WinDefend", "WinDefend", {"status": ("host", "defender")}),
    "windows-backup": ("wbengine", "wbengine", {"backup": ("host", "win_backup")}),
    "veeam-windows": (
        "VeeamEndpointBackupSvc",
        "VeeamEndpointBackupSvc",
        {"service": _SERVICE, "job": ("app", "veeam_windows")},
    ),
}


def _block(units, state="active", sub="running"):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": [{"name": u, "state": state, "sub": sub} for u in units],
        "sockets": [],
        "containers": [],
        "markers": {},
        "ports": [],
    }


def _check(module_id, key):
    return next(c for c in CATALOG.modules[module_id].checks if c.key == key)


def _status(module_id, key, **values):
    """The status the probe checker gives a result of the module's check with these values."""
    module = CATALOG.modules[module_id]
    _, instance, _ = MODULES[module_id]
    config, why = probe_config(module, _check(module_id, key), instance, {"unit": instance}, [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_modules_load_with_their_checks():
    assert CATALOG.errors == ()
    for module_id, (_, _, checks) in MODULES.items():
        got = {c.key: (c.sensor, c.params.get("view")) for c in CATALOG.modules[module_id].checks}
        assert got == checks, module_id


def test_no_check_runs_longer_than_the_agents_limit():
    for module_id in MODULES:
        for check in CATALOG.modules[module_id].checks:
            assert check.timeout_s is None or check.timeout_s <= 30, (module_id, check.key)


@pytest.mark.parametrize("module_id", sorted(MODULES))
def test_the_service_makes_one_instance_and_its_checks_bind_to_it(module_id):
    unit, instance, checks = MODULES[module_id]
    seen = match_inventory(_block([unit, "EventLog"]), CATALOG)
    ours = {k: v for k, v in seen.items() if k[0] == module_id}
    assert ours == {(module_id, instance): {"unit": instance}}
    module = CATALOG.modules[module_id]
    for key in checks:
        config, why = probe_config(
            module, _check(module_id, key), instance, ours[(module_id, instance)], []
        )
        assert why is None, (key, why)
        if config.get("target"):
            assert config["target"]["name"] == instance


@pytest.mark.parametrize("module_id", sorted(set(MODULES) - {"windows-backup"}))
def test_a_stopped_service_finds_nothing(module_id):
    # Also the spooler a domain controller switches off on purpose: no instance, no alarm.
    unit, _, _ = MODULES[module_id]
    stopped = _block([unit], state="inactive", sub="dead")
    assert not any(m == module_id for m, _ in match_inventory(stopped, CATALOG))


def test_the_resting_backup_engine_still_finds_windows_backup():
    # wbengine starts only for a backup; between backups it rests.
    stopped = _block(["wbengine"], state="inactive", sub="dead")
    assert ("windows-backup", "wbengine") in match_inventory(stopped, CATALOG)


def test_a_named_sql_server_instance_is_not_taken():
    # MSSQL$<name> makes no instance key (the "$"); only the default instance is covered.
    assert not any(m == "mssql" for m, _ in match_inventory(_block(["MSSQL$SHOP"]), CATALOG))


@pytest.mark.parametrize(
    ("module_id", "key", "values", "want"),
    [
        (
            "hyperv",
            "vms",
            {
                "vms": 3,
                "vms_running": 2,
                "vms_unhealthy": 0,
                "heartbeat_lost": 0,
                "replication_warning": 0,
                "replication_critical": 0,
                "checkpoints": 0,
            },
            "ok",
        ),
        (
            "hyperv",
            "vms",
            {
                "vms_unhealthy": 0,
                "heartbeat_lost": 0,
                "replication_warning": 0,
                "replication_critical": 0,
                "checkpoints": 2,
                "oldest_checkpoint_age_s": 9 * 86400,
            },
            "ok",
        ),
        ("hyperv", "vms", {"vms_unhealthy": 0, "heartbeat_lost": 1}, "warning"),
        ("hyperv", "vms", {"vms_unhealthy": 0, "replication_warning": 1}, "warning"),
        ("hyperv", "vms", {"vms_unhealthy": 1, "heartbeat_lost": 1}, "critical"),
        ("hyperv", "vms", {"replication_critical": 1, "heartbeat_lost": 0}, "critical"),
        (
            "dfsr",
            "folders",
            {
                "folders": 2,
                "folders_error": 0,
                "folders_not_normal": 1,
                "stopped_events_24h": 0,
                "offline_too_long_24h": 0,
            },
            "ok",
        ),
        ("dfsr", "folders", {"folders_error": 1, "stopped_events_24h": 0}, "critical"),
        ("dfsr", "folders", {"folders_error": 0, "stopped_events_24h": 1}, "critical"),
        ("dfsr", "folders", {"folders_error": 0, "offline_too_long_24h": 1}, "critical"),
        ("mssql", "events", {"errors_24h": 0}, "ok"),
        ("mssql", "events", {"errors_24h": 1}, "warning"),
        (
            "wsus",
            "content",
            {"content_free_bytes": 10, "content_free_pct": 10.0, "errors_24h": 0},
            "ok",
        ),
        ("wsus", "content", {"content_free_pct": 9.9, "errors_24h": 0}, "warning"),
        ("wsus", "content", {"content_free_pct": 4.9, "errors_24h": 0}, "critical"),
        ("wsus", "content", {"content_free_pct": 50.0, "errors_24h": 1}, "warning"),
        (
            "windows-fileserver",
            "storage",
            {
                "disks": 4,
                "disks_unhealthy": 0,
                "vdisks": 1,
                "vdisks_unhealthy": 0,
                "shadow_copies": 0,
                "quotas": 3,
                "quotas_over_90": 2,
                "volumes": 2,
                "volumes_unprotected": 2,
            },
            "ok",
        ),
        ("windows-fileserver", "storage", {"disks_unhealthy": 1, "vdisks_unhealthy": 0}, "warning"),
        (
            "windows-fileserver",
            "storage",
            {"disks_unhealthy": 0, "vdisks_unhealthy": 1},
            "critical",
        ),
        (
            "print-server",
            "queues",
            {"printers": 2, "printers_error": 0, "jobs": 0, "jobs_error": 0},
            "ok",
        ),
        ("print-server", "queues", {"printers_error": 1, "jobs_error": 0}, "warning"),
        (
            "print-server",
            "queues",
            {"printers_error": 0, "jobs_error": 1, "oldest_job_age_s": 600},
            "warning",
        ),
        ("cups", "queues", {"queues": 3, "queues_disabled": 0}, "ok"),
        ("cups", "queues", {"queues": 3, "queues_disabled": 1}, "critical"),
        (
            "defender",
            "status",
            {
                "realtime_on": True,
                "antivirus_on": True,
                "detections_24h": 0,
                "signature_age_d": 1,
                "passive": False,
            },
            "ok",
        ),
        (
            "defender",
            "status",
            {"realtime_on": True, "detections_24h": 0, "signature_age_d": 2},
            "warning",
        ),
        (
            "defender",
            "status",
            {"realtime_on": True, "detections_24h": 0, "signature_age_d": 4},
            "critical",
        ),
        (
            "defender",
            "status",
            {"realtime_on": True, "detections_24h": 1, "signature_age_d": 0},
            "warning",
        ),
        (
            "defender",
            "status",
            {"realtime_on": False, "detections_24h": 0, "signature_age_d": 0},
            "critical",
        ),
        # R-1480: in passive mode real-time protection blocks nothing; off is no finding there.
        (
            "defender",
            "status",
            {"realtime_on": False, "passive": True, "detections_24h": 0, "signature_age_d": 0},
            "ok",
        ),
        (
            "defender",
            "status",
            {"realtime_on": False, "passive": False, "detections_24h": 0, "signature_age_d": 0},
            "critical",
        ),
        # The other rules still hold in passive mode.
        (
            "defender",
            "status",
            {"realtime_on": False, "passive": True, "detections_24h": 0, "signature_age_d": 4},
            "critical",
        ),
        (
            "windows-backup",
            "backup",
            {"last_failed": False, "failures_24h": 0, "last_success_age_s": 129600},
            "ok",
        ),
        # A backup that stopped running fails no more; only its age tells.
        (
            "windows-backup",
            "backup",
            {"last_failed": False, "failures_24h": 0, "last_success_age_s": 129601},
            "warning",
        ),
        # A host that never backed up has no age to rate.
        ("windows-backup", "backup", {"last_failed": False, "failures_24h": 0}, "unknown"),
        ("windows-backup", "backup", {"last_failed": False, "failures_24h": 1}, "warning"),
        ("windows-backup", "backup", {"last_failed": True, "failures_24h": 1}, "critical"),
        (
            "veeam-windows",
            "job",
            {"runs": 1, "last_result": "success", "last_run_age_s": 129600},
            "ok",
        ),
        (
            "veeam-windows",
            "job",
            {"runs": 1, "last_result": "success", "last_run_age_s": 129601},
            "warning",
        ),
        (
            "veeam-windows",
            "job",
            {"runs": 1, "last_result": "warning", "last_run_age_s": 60},
            "warning",
        ),
        (
            "veeam-windows",
            "job",
            {"runs": 1, "last_result": "failed", "last_run_age_s": 60},
            "critical",
        ),
        # Before the first run there is no result to rate.
        ("veeam-windows", "job", {"runs": 0}, "unknown"),
    ],
)
def test_each_rule_fires_at_its_threshold(module_id, key, values, want):
    assert _status(module_id, key, **values) == want


@pytest.mark.parametrize(("state", "want"), [("active", "ok"), ("inactive", "critical")])
def test_a_stopped_role_service_is_critical(state, want):
    assert _status("hyperv", "service", active_state=state, sub_state="dead") == want
