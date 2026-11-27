# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module adminhelper (R-1235): AdminHelper's own compose project is found by any
of its images, each check binds to the container of its service, the file checks read paths
inside their container, and the backup check binds only where pg-backup runs."""

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["adminhelper"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
OWN = "ghcr.io/admincave/adminhelper/"
HOUR = 3600
PG_BACKUP = Path(__file__).resolve().parents[3] / "scripts" / "pg-backup.sh"


def _container(service, image, ports=(), state="running", project="adminhelper"):
    return {
        "id": "id-" + service,
        "name": f"adminhelper-{service}-1",
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": state,
        "health": "healthy",
        "ports": [{"private": p, "public": None, "proto": "tcp"} for p in ports],
        "mounts": [],
    }


STACK = [
    _container("postgres", "postgres:18-alpine"),
    _container("db-init", OWN + "server:0.47.0", state="exited"),
    _container("server", OWN + "server:0.47.0", ports=[8080]),
    _container("scheduler", OWN + "server:0.47.0"),
    _container("gateway", OWN + "gateway:0.47.0", ports=[443, 8444, 8445]),
    _container("ca-issuer", OWN + "ca-issuer:0.47.0", ports=[8090]),
    _container("redis", "redis:8-alpine"),
    _container("frps", OWN + "frps:0.47.0", ports=[7000, 443]),
    _container("monitoring", OWN + "monitoring:0.47.0", ports=[8080]),
    _container("victoria", "victoriametrics/victoria-metrics:v1.155.0", ports=[8428]),
]
WITH_BACKUP = [*STACK, _container("pg-backup", "postgres:18-alpine")]


def _found(containers):
    inv = {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": [],
        "sockets": [],
        "containers": containers,
        "markers": {},
        "ports": [],
    }
    return {k: s for (m, k), s in match_inventory(inv, CATALOG).items() if m == "adminhelper"}


def _bind(check_key, containers=WITH_BACKUP):
    return probe_config(
        MODULE, CHECKS[check_key], "adminhelper", _found(containers)["adminhelper"], containers
    )


def _config(check_key):
    config, why = _bind(check_key)
    assert why is None, why
    return config


def _status(check_key, **values):
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**_config(check_key), "_check_id": "chk"}, report)[0]


def test_the_module_loads_and_never_does_work_in_the_services():
    assert CATALOG.errors == ()
    assert not any(c.test_object or c.credential for c in MODULE.checks)
    # db-init exits after every `up`; the frps container is the frps module's.
    services = {c.target.service for c in MODULE.checks if c.sensor == "container"}
    assert services == {
        "server",
        "scheduler",
        "gateway",
        "ca-issuer",
        "monitoring",
        "postgres",
        "redis",
        "victoria",
    }


def test_each_check_binds_to_the_container_of_its_service():
    names = {key: _config(key)["target"]["name"] for key in CHECKS}
    for key, check in CHECKS.items():
        assert names[key] == f"adminhelper-{check.target.service}-1", key
    assert names["backup"] == "adminhelper-pg-backup-1"
    assert names["metrics_disk"] == "adminhelper-victoria-1"


def test_the_health_checks_ask_the_ports_of_docker_compose():
    assert _config("monitoring_health")["target"]["port_hint"] == 8080
    assert _config("monitoring_scheduler")["target"]["port_hint"] == 8080
    assert _config("monitoring_scheduler")["params"]["path"] == "/health/detail"
    assert _config("monitoring_health")["params"]["path"] == "/health"
    assert _config("ca_issuer_health")["target"]["port_hint"] == 8090
    assert _config("ca_issuer_health")["params"]["path"] == "/healthz"
    assert _config("gateway_certificate")["target"]["port_hint"] == 443


def test_the_file_checks_name_paths_inside_their_containers():
    paths = {
        key: _config(key)["params"].get("path") or _config(key)["params"].get("newest_in")
        for key, check in CHECKS.items()
        if check.sensor in {"certfile", "file_age", "fs"}
    }
    assert paths == {
        "frps_certificate": "/app/frps-certs/frps.crt",
        "ca_root": "/app/data/pki/root.crt",
        "ca_tunnel": "/app/data/pki/tunnel.crt",
        "ca_access": "/app/data/pki/access.crt",
        "ca_internal": "/app/data/pki/internal.crt",
        "backup": "/backups",
        "metrics_disk": "/victoria-metrics-data",
    }


def test_the_backup_check_binds_only_where_pg_backup_runs():
    config, why = _bind("backup", STACK)
    assert config is None
    assert why == "no container for this instance"
    # The other checks bind all the same.
    assert _bind("metrics_disk", STACK)[1] is None


@pytest.mark.parametrize("image", ["server", "gateway", "ca-issuer", "monitoring", "frps"])
def test_any_own_image_finds_the_project(image):
    assert list(_found([_container("x", OWN + image + ":0.47.0")])) == ["adminhelper"]


def test_postgres_redis_and_victoria_alone_are_no_adminhelper():
    assert _found([STACK[0], STACK[6], STACK[9]]) == {}


@pytest.mark.parametrize(
    ("age_h", "want"), [(20, "ok"), (27, "warning"), (49, "warning"), (51, "critical")]
)
def test_the_backup_ages(age_h, want):
    values = {"exists": True, "age_s": age_h * HOUR, "size_bytes": 1 << 20}
    assert _status("backup", **values) == want


def test_an_empty_backup_folder_is_a_warning():
    assert _status("backup", exists=False, size_bytes=0) == "warning"


@pytest.mark.parametrize(
    ("used", "inodes", "want"),
    [
        (79.9, 10.0, "ok"),
        (80.0, 10.0, "warning"),
        (90.0, 10.0, "critical"),
        (50.0, 90.0, "warning"),
    ],
)
def test_the_metrics_disk(used, inodes, want):
    values = {"used_pct": used, "free_bytes": 1 << 30, "inodes_used_pct": inodes}
    assert _status("metrics_disk", **values) == want


@pytest.mark.parametrize(
    ("key", "days", "want"),
    [
        ("gateway_certificate", 31, "ok"),
        ("gateway_certificate", 29, "warning"),
        ("gateway_certificate", 6, "critical"),
        ("frps_certificate", 29, "warning"),
        ("ca_root", 400, "ok"),
        ("ca_root", 364, "warning"),
        ("ca_root", 89, "critical"),
        ("ca_tunnel", 179, "warning"),
        ("ca_internal", 29, "critical"),
    ],
)
def test_the_certificate_days(key, days, want):
    values = {"days_left": days, "not_after": "2030-01-01T00:00:00Z", "issuer": "AdminHelper"}
    assert _status(key, **values) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"status_code": 200, "duration_ms": 3, "data.status": "ok"}, "ok"),
        ({"status_code": 503, "duration_ms": 3}, "critical"),
        ({"status_code": 200, "duration_ms": 3, "data.status": "starting"}, "critical"),
    ],
)
@pytest.mark.parametrize("key", ["monitoring_health", "ca_issuer_health"])
def test_the_health_rules(key, values, want):
    assert _status(key, **values) == want


@pytest.mark.parametrize(
    ("lag", "failed", "want"),
    [
        (0, 0, "ok"),
        (600, 0, "ok"),
        (601, 0, "warning"),
        (1801, 0, "critical"),
        (0, 1, "warning"),
        (1801, 3, "critical"),
    ],
)
def test_the_scheduler_lag_and_the_failed_mails(lag, failed, want):
    values = {
        "status_code": 200,
        "data.scheduler_lag_s": lag,
        "data.mail_failed_24h": failed,
        "data.mail_last_ok_age_s": None,
    }
    assert _status("monitoring_scheduler", **values) == want


def test_an_unreachable_detail_is_critical():
    assert _status("monitoring_scheduler", status_code=503) == "critical"


def _pg_backup(tmp_path, pg_dump_body, role_passwords=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "pg_dump"
    # Like the real one: the output file exists before the connection is tried.
    fake.write_text(
        '#!/bin/sh\nfor a; do case "$a" in --file=*) out="${a#--file=}";; esac; done\n'
        ': > "$out"\n' + pg_dump_body
    )
    fake.chmod(0o755)
    backups = tmp_path / "backups"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "BACKUP_DIR": str(backups)}
    env.pop("BACKUP_DB_PASSWORD", None)
    if role_passwords:
        # pg-backup dumps both databases as the read-only role ah_backup (R-1783).
        env["BACKUP_DB_PASSWORD"] = "pw-backup"
    run = subprocess.run(["sh", str(PG_BACKUP)], env=env, capture_output=True, check=False)
    files = sorted(p.name for p in backups.iterdir() if p.is_file()) if backups.exists() else []
    return run.returncode, files


def test_a_failed_dump_leaves_no_file_the_backup_age_would_count(tmp_path):
    # newest_in counts the newest regular file in /backups: a fresh partial dump of every
    # failed day would keep the age young while no backup succeeds.
    rc, files = _pg_backup(tmp_path, "exit 1\n")
    assert rc != 0
    assert files == []


def test_a_good_dump_lands_in_the_backup_folder(tmp_path):
    rc, files = _pg_backup(tmp_path, "exit 0\n")
    assert rc == 0
    assert len(files) == 2
    assert all(f.endswith(".dump") for f in files)


def test_without_the_role_passwords_the_backup_stops_and_writes_nothing(tmp_path):
    rc, files = _pg_backup(tmp_path, "exit 0\n", role_passwords=False)
    assert rc != 0
    assert files == []
