# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules of a backup host (R-1233): urbackup, backuppc, rsnapshot, veeam, the
repositories of restic, borg and kopia, duplicati and the app backups of GitLab and 3CX.
Their unit or marker finds them, each check binds to the unit or runs on the host, and each
rule fires at its threshold and not below it."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.catalog.loader import load_catalog
from app.catalog.model import Check, Rule
from app.catalog.sensors import PASSWORD_VIEWS, field_allowed, validate_params
from app.check_configs import ProbeConfig
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULES = (
    "urbackup",
    "backuppc",
    "rsnapshot",
    "veeam",
    "restic",
    "borg",
    "kopia",
    "duplicati",
    "gitlab_backup",
    "gitlab_backup_docker",
    "3cx_backup",
)
UNITS = {
    "urbackup": "urbackupsrv.service",
    "backuppc": "backuppc.service",
    "veeam": "veeamservice.service",
}
# A unit of each repository module as a timer would start it; the run check reads its result.
REPO_UNITS = {
    "restic": "restic-backup.service",
    "borg": "borgmatic.service",
    "kopia": "kopia-snapshot.service",
}
APP_BACKUPS = {
    "gitlab_backup": ("gitlab_backup.dir", "/var/opt/gitlab/backups"),
    "gitlab_backup_docker": ("gitlab_backup_docker.dir", "/srv/gitlab/data/backups"),
    "3cx_backup": ("3cx_backup.dir", "/var/lib/3cxpbx/Instance1/Data/Backups"),
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
    if module_id in APP_BACKUPS:
        return _block(markers={APP_BACKUPS[module_id][0]: True}), module_id
    if module_id in REPO_UNITS:
        # Between two runs: a oneshot unit behind a timer rests inactive.
        return _block(units=[_unit(REPO_UNITS[module_id], "inactive")]), REPO_UNITS[module_id]
    if module_id == "duplicati":
        return _block(units=[_unit("duplicati.service")]), "duplicati.service"
    return _block(units=[_unit(UNITS[module_id])]), UNITS[module_id]


def _config(module_id, check_key):
    block, key = _instance(module_id)
    module = CATALOG.modules[module_id]
    check = next(c for c in module.checks if c.key == check_key)
    config, why = probe_config(module, check, key, _found(block, module_id)[key], [])
    assert why is None, why
    return config


def _result(module_id, check_key, result, prev_details=None):
    config = {**_config(module_id, check_key), "_check_id": "chk"}
    report = {"timestamp": STAMP, "probes": {"chk": {"ts": T0, "duration_ms": 40, **result}}}
    return ProbeChecker().evaluate(config, report, prev_details)[0]


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


# --- restic, borg, kopia: the timer unit's last run, the repository with a stored password ---


@pytest.mark.parametrize(
    ("unit", "module_id"),
    [
        ("restic-backup.service", "restic"),
        ("restic.service", "restic"),
        ("restic@home.service", "restic"),
        ("restic-backups-daily.service", "restic"),
        ("borgmatic.service", "borg"),
        ("borgmatic@etc.service", "borg"),
        ("borg-backup.service", "borg"),
        ("kopia-snapshot.service", "kopia"),
    ],
)
@pytest.mark.parametrize("state", ["inactive", "active", "failed"])
def test_a_backup_unit_finds_its_module_also_between_two_runs(unit, module_id, state):
    assert _seen(_block(units=[_unit(unit, state)])) == [module_id]
    assert list(_found(_block(units=[_unit(unit, state)]), module_id)) == [unit]


@pytest.mark.parametrize(
    "unit", ["restic.home.service", "restic@.service", "borgmatic.timer", "myrestic.service"]
)
def test_a_name_outside_the_patterns_finds_no_repository_module(unit):
    assert _seen(_block(units=[_unit(unit, "inactive")])) == []


def test_a_stopped_duplicati_finds_nothing():
    assert _seen(_block(units=[_unit("duplicati.service", "inactive")])) == []


@pytest.mark.parametrize("module_id", sorted(REPO_UNITS))
def test_the_run_check_reads_the_last_run_of_the_unit(module_id):
    config = _config(module_id, "run")
    assert (config["sensor"], config["target"]["name"]) == ("unit", REPO_UNITS[module_id])
    assert config["fields"] == ["active_state", "result", "exec_status", "last_run_age_s"]
    assert config["credential"] is None


RUN_OK = {
    "active_state": "inactive",
    "result": "success",
    "exec_status": 0,
    "last_run_age_s": 3600,
}


@pytest.mark.parametrize("module_id", sorted(REPO_UNITS))
@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"active_state": "activating"}, "ok"),
        ({"last_run_age_s": DAY_AND_TWO_HOURS}, "ok"),
        ({"last_run_age_s": DAY_AND_TWO_HOURS + 1}, "warning"),
        ({"result": "exit-code", "exec_status": 1}, "critical"),
        ({"result": "timeout"}, "critical"),
    ],
)
def test_each_run_rule_fires(module_id, change, want):
    assert _status(module_id, "run", **{**RUN_OK, **change}) == want


@pytest.mark.parametrize(
    ("module_id", "view"),
    [("restic", "restic_latest"), ("borg", "borg_latest"), ("kopia", "kopia_latest")],
)
def test_the_snapshot_check_asks_the_repository_with_the_stored_password(module_id, view):
    config = _config(module_id, "snapshot")
    assert (config["sensor"], config["params"], config["interval_s"]) == (
        "app",
        {"view": view},
        3600,
    )
    assert config["target"]["name"] == REPO_UNITS[module_id]
    assert config["credential"] == {
        "ref": f"{module_id}/{REPO_UNITS[module_id]}/default",
        "use": "password",
    }


@pytest.mark.parametrize("module_id", sorted(REPO_UNITS))
def test_without_a_stored_password_the_snapshot_check_warns(module_id):
    result = {"status": "no_credential", "values": {}, "error": ""}
    assert _result(module_id, "snapshot", result) == "warning"


@pytest.mark.parametrize("module_id", sorted(REPO_UNITS))
@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"has_snapshot": True, "snapshot_age_s": DAY_AND_TWO_HOURS}, "ok"),
        ({"has_snapshot": True, "snapshot_age_s": DAY_AND_TWO_HOURS + 1}, "warning"),
        ({"has_snapshot": False}, "warning"),
    ],
)
def test_each_snapshot_rule_fires(module_id, values, want):
    assert _status(module_id, "snapshot", **values) == want


@pytest.mark.parametrize(("state", "want"), [("active", "ok"), ("failed", "critical")])
def test_duplicati_service_rule(state, want):
    assert _status("duplicati", "service", active_state=state, sub_state="dead") == want


@pytest.mark.parametrize(("healthy", "want"), [(True, "ok"), (False, "critical")])
def test_duplicati_health_rule(healthy, want):
    config = _config("duplicati", "health")
    assert (config["params"], config["credential"]) == ({"view": "duplicati_health"}, None)
    assert _status("duplicati", "health", healthy=healthy) == want


# --- the credential use password goes to a repository view only ---


def _check(sensor, params, target, use):
    return {
        "key": "c",
        "name": "c",
        "sensor": sensor,
        "params": params,
        "target": target,
        "interval": 3600,
        "fields": ["has_snapshot"] if sensor == "app" else ["status_code"],
        "credential": {"slot": "default", "use": use},
    }


@pytest.mark.parametrize("view", sorted(PASSWORD_VIEWS))
def test_a_repository_view_takes_the_password(view):
    Check.model_validate(_check("app", {"view": view}, {"kind": "unit"}, "password"))


def test_the_password_goes_to_no_other_sensor_or_view():
    http = _check("http", {}, {"kind": "unit", "port_hint": 80, "scheme": "http"}, "password")
    with pytest.raises(ValidationError, match="only for the views"):
        Check.model_validate(http)
    health = {
        **_check("app", {"view": "duplicati_health"}, {"kind": "unit"}, "password"),
        "fields": ["healthy"],
    }
    with pytest.raises(ValidationError, match="only for the views"):
        Check.model_validate(health)


def test_a_probe_check_takes_the_password_like_the_catalog():
    config = {**_config("restic", "snapshot")}
    config["credential"] = {"ref": "restic/restic-backup.service/default", "use": "password"}
    ProbeConfig.model_validate(config)
    config["params"] = {"view": "duplicati_health"}
    config["fields"], config["rules"] = ["healthy"], []
    with pytest.raises(ValidationError, match="only for the views"):
        ProbeConfig.model_validate(config)


# --- app backups: the newest file of a folder, its age and a fall of its size ---


@pytest.mark.parametrize("module_id", sorted(APP_BACKUPS))
def test_an_app_backup_folder_makes_one_instance_with_its_newest_file(module_id):
    marker, folder = APP_BACKUPS[module_id]
    assert _found(*_instance(module_id)) == {module_id: {"matched_by": [f"marker:{marker}"]}}
    config = _config(module_id, "newest")
    assert (config["sensor"], config["params"], config["target"]) == (
        "file_age",
        {"newest_in": folder},
        None,
    )
    assert config["interval_s"] == 3600


def test_gitlab_finds_its_backups_also_by_its_package():
    assert CATALOG.modules["gitlab_backup"].detect.markers[0].packages == ["gitlab-ce", "gitlab-ee"]


@pytest.mark.parametrize("module_id", ["gitlab_backup", "gitlab_backup_docker"])
def test_gitlab_says_the_secrets_are_not_in_the_backup(module_id):
    assert "gitlab-secrets.json" in CATALOG.modules[module_id].description


@pytest.mark.parametrize("present", [None, False])
def test_without_the_folder_there_is_no_app_backup(present):
    markers = {} if present is None else {m: present for m, _ in APP_BACKUPS.values()}
    assert _seen(_block(markers=markers)) == []


NEWEST_OK = {"exists": True, "age_s": DAY_AND_TWO_HOURS, "size_bytes": 1000}


@pytest.mark.parametrize("module_id", sorted(APP_BACKUPS))
@pytest.mark.parametrize(
    ("values", "want"),
    [
        (NEWEST_OK, "ok"),
        ({**NEWEST_OK, "age_s": DAY_AND_TWO_HOURS + 1}, "warning"),
        ({"exists": False}, "warning"),
    ],
)
def test_each_app_backup_rule_fires(module_id, values, want):
    assert _status(module_id, "newest", **values) == want


def _after(module_id, size_before, size_now):
    prev = {"measured_ts": T0 - 3600, "values": {**NEWEST_OK, "size_bytes": size_before}}
    result = {"status": "ok", "values": {**NEWEST_OK, "size_bytes": size_now}, "error": ""}
    return _result(module_id, "newest", result, prev)


@pytest.mark.parametrize("module_id", sorted(APP_BACKUPS))
@pytest.mark.parametrize(
    ("before", "now", "want"),
    [
        (1000, 500, "ok"),
        (1000, 499, "warning"),
        (1000, 0, "warning"),
        (1000, 3000, "ok"),
        (0, 0, "ok"),
    ],
)
def test_a_backup_half_the_size_of_the_last_run_warns(module_id, before, now, want):
    assert _after(module_id, before, now) == want


def test_a_fall_of_the_size_is_named_in_percent():
    config = {**_config("gitlab_backup", "newest"), "_check_id": "chk"}
    prev = {"measured_ts": T0 - 3600, "values": {**NEWEST_OK, "size_bytes": 1000}}
    result = {"status": "ok", "values": {**NEWEST_OK, "size_bytes": 200}, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": {"ts": T0, "duration_ms": 40, **result}}}
    _, text, _ = ProbeChecker().evaluate(config, report, prev)
    assert "size_bytes fell by 80 % (drop_pct_gt 50)" in text


def test_the_first_run_has_nothing_to_compare():
    assert _after("gitlab_backup", None, 10) == "ok"


@pytest.mark.parametrize("value", [0, 100, -5, 150, "50", True])
def test_drop_pct_gt_takes_a_percentage_only(value):
    with pytest.raises(ValidationError):
        Rule.model_validate(
            {"field": "size_bytes", "op": "drop_pct_gt", "value": value, "level": "warning"}
        )


@pytest.mark.parametrize(
    ("params", "want"),
    [
        ({"path": "/etc/x"}, {"path": "/etc/x"}),
        ({"newest_in": "/var/backups"}, {"newest_in": "/var/backups"}),
    ],
)
def test_file_age_takes_a_path_or_a_folder(params, want):
    assert validate_params("file_age", params) == want


@pytest.mark.parametrize(
    "params", [{}, {"path": "/a", "newest_in": "/b"}, {"newest_in": "backups"}, {"path": None}]
)
def test_file_age_takes_exactly_one_absolute_path(params):
    with pytest.raises(ValidationError):
        validate_params("file_age", params)
