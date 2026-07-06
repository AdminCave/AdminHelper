# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Alert-decision logic of the plugin checkers (Proxmox/ZFS/Docker). These produce field false
alarms or swallowed alarms if they drift — e.g. a regression dropping DEGRADED from the critical set
would never be noticed without a test (6.53)."""

from app.checkers.plugins import DockerHealthChecker, ProxmoxBackupChecker, ZfsHealthChecker


# --- ZfsHealthChecker ---
def test_zfs_degraded_pool_is_critical():
    r = {"zfs": {"pools": [{"name": "tank", "health": "DEGRADED", "capacity_percent": 10}]}}
    status, msg, _ = ZfsHealthChecker().evaluate({}, r)
    assert status == "critical" and "DEGRADED" in msg


def test_zfs_over_capacity_is_critical():
    r = {"zfs": {"pools": [{"name": "tank", "health": "ONLINE", "capacity_percent": 95}]}}
    status, _, _ = ZfsHealthChecker().evaluate({"capacity_crit": 90}, r)
    assert status == "critical"


def test_zfs_healthy_pool_is_ok():
    r = {"zfs": {"pools": [{"name": "tank", "health": "ONLINE", "capacity_percent": 20}]}}
    status, _, _ = ZfsHealthChecker().evaluate({}, r)
    assert status == "ok"


# --- ProxmoxBackupChecker ---
def test_proxmox_missing_backup_is_critical():
    r = {"proxmox": {"vms": [{"vmid": 100, "status": "running", "last_backup_ts": None}]}}
    status, _, _ = ProxmoxBackupChecker().evaluate({}, r)
    assert status == "critical"


def test_proxmox_outdated_backup_is_warning(monkeypatch):
    monkeypatch.setattr("app.checkers.plugins.time.time", lambda: 1_000_000.0)
    # 30h old with the default 26h threshold -> outdated (warning, not missing).
    r = {
        "proxmox": {
            "vms": [{"vmid": 100, "status": "running", "last_backup_ts": 1_000_000.0 - 30 * 3600}]
        }
    }
    status, _, _ = ProxmoxBackupChecker().evaluate({}, r)
    assert status == "warning"


def test_proxmox_excludes_stopped_and_listed_vmids():
    r = {
        "proxmox": {
            "vms": [
                {"vmid": 100, "status": "stopped", "last_backup_ts": None},  # excluded: stopped
                {"vmid": 999, "status": "running", "last_backup_ts": None},  # excluded: vmid
            ]
        }
    }
    status, _, _ = ProxmoxBackupChecker().evaluate({"exclude_vmids": [999]}, r)
    assert status == "ok"  # both excluded -> no missing backups reported


# --- DockerHealthChecker ---
def test_docker_stopped_with_restart_policy_is_critical():
    r = {
        "docker": {
            "containers": [
                {"name": "db", "state": "exited", "status": "", "restart_policy": "always"}
            ]
        }
    }
    status, _, _ = DockerHealthChecker().evaluate({}, r)
    assert status == "critical"


def test_docker_unhealthy_is_warning():
    r = {
        "docker": {
            "containers": [
                {
                    "name": "web",
                    "state": "running",
                    "status": "Up (unhealthy)",
                    "restart_policy": "no",
                }
            ]
        }
    }
    status, _, _ = DockerHealthChecker().evaluate({}, r)
    assert status == "warning"


def test_docker_ignored_container_is_skipped():
    r = {
        "docker": {
            "containers": [
                {"name": "watchtower", "state": "exited", "status": "", "restart_policy": "always"}
            ]
        }
    }
    status, _, _ = DockerHealthChecker().evaluate({"ignore_containers": ["watchtower"]}, r)
    assert status == "ok"  # the only problem container is ignored
