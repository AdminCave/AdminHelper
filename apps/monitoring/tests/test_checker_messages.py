# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The checker messages are English (R-0422): `message` goes as it is into the
dashboard, the bell and the notifications, and the desktop shows it untranslated.
One case per message path, compared exactly; status rides along so a case cannot
pass on the wrong path."""

import time
from datetime import datetime, timedelta

import pytest

from app.checkers import agent
from app.checkers.agent import AgentPingChecker, AgentResourcesChecker, ServiceProcessChecker
from app.checkers.plugins import DockerHealthChecker, ProxmoxBackupChecker, ZfsHealthChecker
from app.checkers.smart import SmartHealthChecker

NOW = datetime(2026, 7, 19, 12, 0, 0)


@pytest.fixture(autouse=True)
def frozen_liveness(monkeypatch):
    """agent_ping reads the module-global liveness maps and the wall clock; one agent
    reported 20 minutes ago, one 2 minutes ago. No monotonic stamp, so the clock-jump
    correction stays out of the way."""
    monkeypatch.setattr(
        agent,
        "_last_report",
        {"srv-stale": NOW - timedelta(minutes=20), "srv-fresh": NOW - timedelta(minutes=2)},
    )
    monkeypatch.setattr(agent, "_last_report_mono", {})
    monkeypatch.setattr(agent, "utcnow_naive", lambda: NOW)


def _ping(config):
    return AgentPingChecker().run(config)


def _resources(report):
    return AgentResourcesChecker().evaluate({}, report)


def _services(config, report):
    return ServiceProcessChecker().evaluate(config, report)


def _auto(systemd):
    return _services({"mode": "auto"}, {"systemd": systemd})


def _listed(names, report):
    return _services({"mode": "list", "services": names}, report)


def _watch(**running):
    return {"services": [{"name": n, "running": r} for n, r in running.items()]}


def _vm(vmid, vm_type, name, last_backup_ts):
    return {
        "vmid": vmid,
        "type": vm_type,
        "name": name,
        "status": "running",
        "last_backup_ts": last_backup_ts,
    }


def _proxmox(*vms):
    return ProxmoxBackupChecker().evaluate({}, {"proxmox": {"vms": list(vms)}})


def _hours_ago(hours):
    return time.time() - hours * 3600


def _zfs(*pools):
    pool_list = [{"name": n, "health": "ONLINE", "capacity_percent": c} for n, c in pools]
    return ZfsHealthChecker().evaluate({}, {"zfs": {"pools": pool_list}})


def _smart(smartctl_status=0):
    disk = {
        "device": "/dev/sda",
        "model": "X",
        "protocol": "ATA",
        "kind": "HDD",
        "temp_c": 30,
        "smartctl_status": smartctl_status,
    }
    return SmartHealthChecker().evaluate({}, {"smart": [disk]})


_SDA = "/dev/sda (X)"
_LIST_ERROR = "sc query failed: sc did not start"
_AUTO_ERROR = "systemctl list-units failed: exit status 1"

CASES = [
    # agent_ping
    pytest.param(lambda: _ping({}), "unknown", "No server_id configured", id="ping-no-server-id"),
    pytest.param(
        lambda: _ping({"server_id": "srv-new"}),
        "unknown",
        "No agent report received yet",
        id="ping-no-report",
    ),
    pytest.param(
        lambda: _ping({"server_id": "srv-stale", "stale_minutes": 15}),
        "critical",
        "Agent unreachable for 20 min (limit: 15 min)",
        id="ping-stale",
    ),
    pytest.param(
        lambda: _ping({"server_id": "srv-fresh", "stale_minutes": 15}),
        "ok",
        "Agent active (last report 120s ago)",
        id="ping-fresh",
    ),
    # agent_resources
    pytest.param(
        lambda: AgentResourcesChecker().run({}),
        "unknown",
        "Waiting for agent data",
        id="resources-waiting",
    ),
    pytest.param(lambda: _resources({}), "unknown", "No resource data", id="resources-no-data"),
    # service_process, auto mode
    pytest.param(
        lambda: ServiceProcessChecker().run({}),
        "unknown",
        "Waiting for agent data",
        id="services-waiting",
    ),
    pytest.param(
        lambda: _services({"mode": "auto"}, {}),
        "unknown",
        "No service data in report",
        id="auto-no-data",
    ),
    pytest.param(
        lambda: _auto({"failed": ["a.service"], "enabled_inactive": ["b.service"]}),
        "critical",
        "Failed: a.service; Inactive (autostart): b.service",
        id="auto-failed-and-inactive",
    ),
    pytest.param(
        lambda: _auto({"failed": [], "enabled_inactive": ["b.service"]}),
        "warning",
        "Inactive (autostart): b.service",
        id="auto-inactive",
    ),
    pytest.param(
        lambda: _auto({"failed": [], "enabled_inactive": [], "error": _AUTO_ERROR}),
        "unknown",
        f"Services not queryable: {_AUTO_ERROR}",
        id="auto-not-queryable",
    ),
    pytest.param(
        lambda: _auto({"failed": [], "enabled_inactive": []}),
        "ok",
        "All services OK",
        id="auto-ok",
    ),
    # service_process, list mode
    pytest.param(
        lambda: _listed([], {}),
        "ok",
        "No services configured",
        id="list-none-configured",
    ),
    pytest.param(
        lambda: _listed(["nginx", "nginxx"], _watch(nginx=False)),
        "critical",
        "Services not active: nginx; no data: nginxx",
        id="list-down-and-no-data",
    ),
    pytest.param(
        lambda: _listed(["nginx"], {}),
        "unknown",
        "Services without data: nginx",
        id="list-no-data",
    ),
    pytest.param(
        lambda: _listed(["nginx"], {"systemd": {"error": _LIST_ERROR}}),
        "unknown",
        f"Services without data: nginx; Services not queryable: {_LIST_ERROR}",
        id="list-no-data-not-queryable",
    ),
    pytest.param(
        lambda: _listed(["nginx", "cron", "nginxx"], _watch(nginx=True, cron=True)),
        "ok",
        "2 services active; no data: nginxx",
        id="list-active-and-no-data",
    ),
    pytest.param(
        lambda: _listed(["nginx", "cron"], _watch(nginx=True, cron=True)),
        "ok",
        "All 2 services active",
        id="list-all-active",
    ),
    # proxmox_backup
    pytest.param(
        lambda: ProxmoxBackupChecker().run({}),
        "unknown",
        "Waiting for agent data",
        id="proxmox-waiting",
    ),
    pytest.param(
        lambda: ProxmoxBackupChecker().evaluate({}, {}),
        "unknown",
        "No Proxmox data in report",
        id="proxmox-no-data",
    ),
    pytest.param(lambda: _proxmox(), "ok", "No VMs/CTs found", id="proxmox-no-vms"),
    pytest.param(
        lambda: _proxmox(_vm(101, "qemu", "a", None), _vm(102, "lxc", "b", _hours_ago(30))),
        "critical",
        "No backup: QEMU 101 (a); Outdated: LXC 102 (b): 30h old",
        id="proxmox-missing-and-outdated",
    ),
    pytest.param(
        lambda: _proxmox(_vm(102, "lxc", "b", _hours_ago(30))),
        "warning",
        "Outdated backups: LXC 102 (b): 30h old",
        id="proxmox-outdated",
    ),
    pytest.param(
        lambda: _proxmox(_vm(101, "qemu", "a", _hours_ago(1))),
        "ok",
        "All 1 VMs/CTs have up-to-date backups",
        id="proxmox-ok",
    ),
    # zfs_health
    pytest.param(
        lambda: ZfsHealthChecker().run({}),
        "unknown",
        "Waiting for agent data",
        id="zfs-waiting",
    ),
    pytest.param(
        lambda: ZfsHealthChecker().evaluate({}, {}),
        "unknown",
        "No ZFS data in report",
        id="zfs-no-data",
    ),
    pytest.param(lambda: _zfs(), "ok", "No ZFS pools found", id="zfs-no-pools"),
    pytest.param(
        lambda: _zfs(("tank", 95)), "critical", "tank: 95% full (>=90%)", id="zfs-capacity-crit"
    ),
    pytest.param(
        lambda: _zfs(("tank", 85)), "warning", "tank: 85% full (>=80%)", id="zfs-capacity-warn"
    ),
    pytest.param(
        lambda: _zfs(("tank", 20), ("backup", 55)),
        "ok",
        "All pools ONLINE: tank 20%, backup 55%",
        id="zfs-ok",
    ),
    # docker_health
    pytest.param(
        lambda: DockerHealthChecker().run({}),
        "unknown",
        "Waiting for agent data",
        id="docker-waiting",
    ),
    # smart_health
    pytest.param(
        lambda: SmartHealthChecker().run({}),
        "unknown",
        "Waiting for agent data",
        id="smart-waiting",
    ),
    pytest.param(
        lambda: SmartHealthChecker().evaluate({}, {}),
        "ok",
        "No SMART data (VM or smartctl not available)",
        id="smart-no-data",
    ),
    pytest.param(
        lambda: _smart(0x10),
        "critical",
        f"SMART problems: {_SDA}: prefail attribute below threshold (smartctl 0x10)",
        id="smart-prefail",
    ),
    pytest.param(
        lambda: _smart(0x20),
        "warning",
        f"SMART warnings: {_SDA}: threshold exceeded in the past (smartctl 0x20)",
        id="smart-past-threshold",
    ),
    pytest.param(
        lambda: _smart(0x40),
        "warning",
        f"SMART warnings: {_SDA}: error log entries (smartctl 0x40)",
        id="smart-error-log",
    ),
    pytest.param(
        lambda: _smart(0x80),
        "warning",
        f"SMART warnings: {_SDA}: self-test failed (smartctl 0x80)",
        id="smart-self-test",
    ),
    pytest.param(
        lambda: _smart(0x10 | 0x20),
        "critical",
        f"SMART problems: {_SDA}: prefail attribute below threshold (smartctl 0x10); "
        f"warnings: {_SDA}: threshold exceeded in the past (smartctl 0x20)",
        id="smart-problems-and-warnings",
    ),
    pytest.param(lambda: _smart(), "ok", "All 1 disks SMART OK", id="smart-ok"),
]


@pytest.mark.parametrize(("call", "status", "message"), CASES)
def test_push_checker_message_is_english(call, status, message):
    got_status, got_message, _ = call()
    assert (got_status, got_message) == (status, message)
