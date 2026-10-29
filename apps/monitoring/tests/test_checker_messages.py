# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The checker messages are English (R-0422): `message` goes as it is into the
dashboard, the bell and the notifications, and the desktop shows it untranslated.
The same holds for what the check engine writes into MonitorState.message. One
case per message path, compared exactly; status rides along so a case cannot pass
on the wrong path."""

import socket
import subprocess
import time
import unicodedata
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.check_engine as ce
import app.core.database as database_mod
from app.checkers import agent, get_checker
from app.checkers import forecast as forecast_mod
from app.checkers import http as http_mod
from app.checkers import ping as ping_mod
from app.checkers import tcp as tcp_mod
from app.checkers.agent import AgentPingChecker, AgentResourcesChecker, ServiceProcessChecker
from app.checkers.plugins import DockerHealthChecker, ProxmoxBackupChecker, ZfsHealthChecker
from app.checkers.smart import SmartHealthChecker
from app.checkers.system import SystemStateChecker
from app.core.ssrf import Target, UrlVerdict
from app.core.time import utcnow_naive
from app.models import Base, MonitorCheck, MonitorState

from ._helpers import no_env_proxy

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


def _system(**fields):
    """A system_state block 30 min after boot: the clock is rated."""
    report = {"uptime_seconds": 1800, "system_state": fields}
    return SystemStateChecker().evaluate({}, report)


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
        lambda: _auto({"failed": ["a.service", "data.mount"], "enabled_inactive": ["b.service"]}),
        "critical",
        "Failed: a.service; Failed units: data.mount; Inactive (autostart): b.service",
        id="auto-failed-service-unit-and-inactive",
    ),
    pytest.param(
        lambda: _auto({"failed": ["data.mount"], "enabled_inactive": ["b.service"]}),
        "warning",
        "Failed units: data.mount; Inactive (autostart): b.service",
        id="auto-failed-unit-and-inactive",
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
    pytest.param(
        lambda: ProxmoxBackupChecker().evaluate(
            {},
            {
                "proxmox": {
                    "available": False,
                    "error": "backup_index_incomplete",
                    "error_message": "backup storage nas not active",
                }
            },
        ),
        "warning",
        "Proxmox unavailable (backup_index_incomplete): backup storage nas not active",
        id="proxmox-unavailable",
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
    # system_state
    pytest.param(
        lambda: SystemStateChecker().run({}),
        "unknown",
        "Waiting for agent data",
        id="system-waiting",
    ),
    pytest.param(
        lambda: SystemStateChecker().evaluate({}, {}),
        "ok",
        "Not evaluated: no system state in report",
        id="system-no-data",
    ),
    pytest.param(
        lambda: _system(reboot_required=True), "warning", "Reboot required", id="system-reboot"
    ),
    pytest.param(
        lambda: _system(time_synchronized=False),
        "warning",
        "Clock not synchronized",
        id="system-time-sync",
    ),
    pytest.param(
        lambda: _system(security_updates=3),
        "warning",
        "3 security updates pending",
        id="system-security-updates",
    ),
    pytest.param(
        lambda: _system(oom_kills=2),
        "warning",
        "2 OOM kills since last report",
        id="system-oom",
    ),
    pytest.param(
        lambda: _system(
            reboot_required=True, time_synchronized=False, security_updates=3, oom_kills=2
        ),
        "warning",
        "Reboot required; Clock not synchronized; 3 security updates pending; "
        "2 OOM kills since last report",
        id="system-all",
    ),
    pytest.param(
        lambda: _system(
            reboot_required=False, time_synchronized=True, security_updates=0, oom_kills=0
        ),
        "ok",
        "System state OK",
        id="system-ok",
    ),
]


@pytest.mark.parametrize(("call", "status", "message"), CASES)
def test_push_checker_message_is_english(call, status, message):
    got_status, got_message, _ = call()
    assert (got_status, got_message) == (status, message)


# --- pull checkers: the network is faked in each case ---

# A public IP literal: the SSRF guard lets it through without DNS.
_PUBLIC = "http://93.184.216.34/"


def _reply(status_code, text="", location=None):
    headers = {"location": location} if location else {}

    def respond(_transport, request):
        # Streamed, as a real transport hands a body over: the HTTP checker reads the raw
        # stream, and a body given whole has been read from it already.
        return httpx.Response(
            status_code, content=iter([text.encode()]), headers=headers, request=request
        )

    return respond


def _raise(exc):
    def respond(*args, **kwargs):
        raise exc

    return respond


def _http(mp, respond, **config):
    # Answered below the pin, where the connection would be made; without a proxy from
    # the shell, so the request takes the pinned path.
    no_env_proxy(mp)
    mp.setattr(httpx.HTTPTransport, "handle_request", respond)
    return http_mod.HttpChecker().run({"url": _PUBLIC, **config})


def _icmp(mp, run, target="host.example"):
    mp.setattr(
        ping_mod,
        "subprocess",
        SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired),
    )
    return ping_mod.PingChecker().run({"target": target, "timeout": 5})


def _ping_result(returncode, stdout=""):
    return lambda *args, **kwargs: SimpleNamespace(returncode=returncode, stdout=stdout)


class _Conn:
    def close(self):
        pass


def _tcp(mp, connect):
    clock = iter([0.0, 0.0125])
    mp.setattr(
        tcp_mod, "socket", SimpleNamespace(create_connection=connect, timeout=socket.timeout)
    )
    mp.setattr(tcp_mod, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    return tcp_mod.TcpChecker().run({"target": "db.example", "port": 5432, "timeout": 5})


def _private(mp):
    mp.setattr(http_mod, "check_target", lambda url: Target(UrlVerdict.PRIVATE, "93.184.216.34"))
    return http_mod.HttpChecker().run({"url": _PUBLIC})


PULL_CASES = [
    # http
    pytest.param(
        lambda mp: http_mod.HttpChecker().run({}), "unknown", "No URL given", id="http-no-url"
    ),
    pytest.param(
        _private,
        "unknown",
        "URL points to a private/reserved address, rejected by the SSRF guard",
        id="http-private-url",
    ),
    pytest.param(
        lambda mp: _http(mp, _reply(302, location="http://127.0.0.1:8428/")),
        "critical",
        "Redirect to a private/reserved address, rejected by the SSRF guard",
        id="http-private-redirect",
    ),
    pytest.param(
        lambda mp: _http(mp, _reply(302, location="http://93.184.216.35/")),
        "critical",
        "Too many redirects (>5)",
        id="http-too-many-redirects",
    ),
    pytest.param(
        lambda mp: _http(mp, _reply(500), verify_ssl=False),
        "critical",
        "Status 500 (expected 200) [TLS verification disabled]",
        id="http-status-tls-off",
    ),
    pytest.param(
        lambda mp: _http(mp, _reply(200, text="hello"), search_string="goodbye"),
        "critical",
        "Text 'goodbye' not found in response",
        id="http-text-missing",
    ),
    pytest.param(
        lambda mp: _http(mp, _raise(httpx.TimeoutException("t"))),
        "critical",
        "Timeout after 10s",
        id="http-timeout",
    ),
    pytest.param(
        lambda mp: _http(mp, _raise(httpx.ConnectError("refused"))),
        "critical",
        "Connection failed: refused",
        id="http-connect-error",
    ),
    pytest.param(
        lambda mp: _http(mp, _raise(ValueError("weird"))),
        "unknown",
        "Error: weird",
        id="http-other-error",
    ),
    # ping
    pytest.param(
        lambda mp: ping_mod.PingChecker().run({}), "unknown", "No target given", id="ping-no-target"
    ),
    pytest.param(
        lambda mp: ping_mod.PingChecker().run({"target": "a;b"}),
        "unknown",
        "Invalid target (only hostnames and IPs allowed)",
        id="ping-invalid-target",
    ),
    pytest.param(
        lambda mp: _icmp(mp, _ping_result(0, "64 bytes from h: icmp_seq=1 time=12.5 ms")),
        "ok",
        "Reachable (12.5 ms)",
        id="ping-reachable-rtt",
    ),
    pytest.param(lambda mp: _icmp(mp, _ping_result(0)), "ok", "Reachable", id="ping-reachable"),
    pytest.param(
        lambda mp: _icmp(mp, _ping_result(1)),
        "critical",
        "host.example unreachable",
        id="ping-unreachable",
    ),
    pytest.param(
        lambda mp: _icmp(mp, _raise(subprocess.TimeoutExpired("ping", 7))),
        "critical",
        "Timeout after 5s",
        id="ping-timeout",
    ),
    pytest.param(
        lambda mp: _icmp(mp, _raise(OSError("ping missing"))),
        "unknown",
        "Error: ping missing",
        id="ping-error",
    ),
    # tcp
    pytest.param(
        lambda mp: tcp_mod.TcpChecker().run({"target": "db.example"}),
        "unknown",
        "Target or port missing",
        id="tcp-missing",
    ),
    pytest.param(
        lambda mp: _tcp(mp, lambda *args, **kwargs: _Conn()),
        "ok",
        "Port 5432 open (12.5 ms)",
        id="tcp-open",
    ),
    pytest.param(
        lambda mp: _tcp(mp, _raise(socket.timeout("timed out"))),
        "critical",
        "Port 5432: timeout after 5s",
        id="tcp-timeout",
    ),
    pytest.param(
        lambda mp: _tcp(mp, _raise(ConnectionRefusedError())),
        "critical",
        "Port 5432: connection refused",
        id="tcp-refused",
    ),
]


@pytest.mark.parametrize(("call", "status", "message"), PULL_CASES)
def test_pull_checker_message_is_english(monkeypatch, call, status, message):
    got_status, got_message, _ = call(monkeypatch)
    assert (got_status, got_message) == (status, message)


# --- lists in a message: at most 10 entries and 1000 characters, then "(+N more)" (R-0517) ---
# The limits are written out, not imported, so a changed limit turns these cases red.

_SEPARATORS = pytest.mark.parametrize("sep", [", ", "; "], ids=["comma", "semicolon"])


@_SEPARATORS
@pytest.mark.parametrize(("count", "named"), [(0, 0), (1, 1), (10, 10), (11, 10), (500, 10)])
def test_join_capped_names_at_most_ten_entries(sep, count, named):
    entries = [f"e{i}" for i in range(count)]
    more = f" (+{count - named} more)" if count > named else ""
    assert agent.join_capped(entries, sep) == sep.join(entries[:named]) + more


def test_join_capped_keeps_an_empty_entry():
    assert agent.join_capped(["", "a"], ", ") == ", a"


@pytest.mark.parametrize(
    "entries",
    [["a" * 600, "b" * 600, "c" * 600], ["a" * 600, "b" * 600, "c"]],
    ids=["three-long", "short-behind-long"],
)
def test_join_capped_cuts_each_entry_to_500_characters(entries):
    # The first entry always goes in; a second cut one would make 500 + 2 + 500 = 1002
    # characters. The order holds: a short entry behind the one that did not fit is counted.
    assert agent.join_capped(entries, ", ") == "a" * 499 + "… (+2 more)"


@_SEPARATORS
def test_join_capped_names_at_most_1000_characters(sep):
    # Two entries of 499 and their separator are exactly 1000 characters.
    entries = ["a" * 499, "b" * 499, "c" * 499, "d" * 499]
    assert agent.join_capped(entries, sep) == "a" * 499 + sep + "b" * 499 + " (+2 more)"


def _first_ten(entries, sep=", "):
    """Twelve entries as a message names them: the first ten, the other two counted."""
    return sep.join(entries[:10]) + " (+2 more)"


def _vms(first_vmid, last_backup_ts, count):
    return [_vm(first_vmid + i, "qemu", f"vm{i}", last_backup_ts) for i in range(count)]


def _pools(capacity, count):
    return [(f"p{i}", capacity) for i in range(count)]


def _containers(count, *states):
    containers = [
        {"id": f"{state}{i}", "name": f"{state}{i}", "state": state}
        for state in states
        for i in range(count)
    ]
    return DockerHealthChecker().evaluate({}, {"docker": {"containers": containers}})


def _smart_disks(smartctl_status, count):
    disks = [
        {
            "device": f"/dev/d{i}",
            "model": "X",
            "protocol": "ATA",
            "kind": "HDD",
            "temp_c": 30,
            "smartctl_status": smartctl_status,
        }
        for i in range(count)
    ]
    return SmartHealthChecker().evaluate({}, {"smart": disks})


def _full_disks(count):
    disks = [{"mount": f"/m{i}", "percent": 95} for i in range(count)]
    return _resources({"resources": {"disks": disks}})


def _filling_mounts(mp, count):
    # 42 % rising 2 pp/h over 24 h: 90 % now, full in ~5 h, below crit_hours 8.
    values = [[i * 3600.0, str(42.0 + 2.0 * i)] for i in range(25)]
    result = [{"metric": {"mount": f"/m{i}"}, "values": values} for i in range(count)]
    mp.setattr(forecast_mod.victoria, "query_range", lambda **kw: {"data": {"result": result}})
    return forecast_mod.DiskForecastChecker().run({"server_id": "srv-1"})


_NO_BACKUP = [f"QEMU {101 + i} (vm{i})" for i in range(12)]
_OUTDATED = [f"QEMU {201 + i} (vm{i}): 30h old" for i in range(12)]
_POOLS_FULL = [f"p{i}: 95% full (>=90%)" for i in range(12)]
_POOLS_OK = [f"p{i} 20%" for i in range(12)]
_DEAD = [f"dead{i}: dead" for i in range(12)]
_PAUSED = [f"paused{i}: paused" for i in range(12)]
_PREFAIL = [f"/dev/d{i} (X): prefail attribute below threshold (smartctl 0x10)" for i in range(12)]
_PAST = [f"/dev/d{i} (X): threshold exceeded in the past (smartctl 0x20)" for i in range(12)]
_DISKS_FULL = [f"Disk /m{i} 95% (>=95%)" for i in range(12)]
_FAILED = [f"f{i}.service" for i in range(12)]
_FAILED_UNITS = [f"m{i}.mount" for i in range(12)]
_INACTIVE = [f"i{i}.service" for i in range(12)]
_DOWN = [f"d{i}" for i in range(12)]
_NODATA = [f"n{i}" for i in range(12)]
_FILLING = [f"/m{i} full in ~5.0h" for i in range(12)]
_NOT_RUNNING = "(0 running, 0 stopped)"

# Each place that joins a list into a message: twelve entries name ten and count two, the
# status stays; exactly ten read as before, without the count.
LIST_CASES = [
    # proxmox_backup
    pytest.param(
        lambda mp: _proxmox(*_vms(101, None, 12), *_vms(201, _hours_ago(30), 12)),
        "critical",
        f"No backup: {_first_ten(_NO_BACKUP)}; Outdated: {_first_ten(_OUTDATED)}",
        id="proxmox-12-missing-and-outdated",
    ),
    pytest.param(
        lambda mp: _proxmox(*_vms(201, _hours_ago(30), 12)),
        "warning",
        f"Outdated backups: {_first_ten(_OUTDATED)}",
        id="proxmox-12-outdated",
    ),
    pytest.param(
        lambda mp: _proxmox(*_vms(101, None, 10)),
        "critical",
        "No backup: " + ", ".join(_NO_BACKUP[:10]),
        id="proxmox-10-missing",
    ),
    # zfs_health
    pytest.param(
        lambda mp: _zfs(*_pools(95, 12)),
        "critical",
        _first_ten(_POOLS_FULL, "; "),
        id="zfs-12-problems",
    ),
    pytest.param(
        lambda mp: _zfs(*_pools(20, 12)),
        "ok",
        f"All pools ONLINE: {_first_ten(_POOLS_OK)}",
        id="zfs-12-pools-ok",
    ),
    pytest.param(
        lambda mp: _zfs(*_pools(95, 10)),
        "critical",
        "; ".join(_POOLS_FULL[:10]),
        id="zfs-10-problems",
    ),
    # docker_health
    pytest.param(
        lambda mp: _containers(12, "dead", "paused"),
        "critical",
        f"Container problems: {_first_ten(_DEAD)}; warnings: {_first_ten(_PAUSED)} {_NOT_RUNNING}",
        id="docker-12-problems-and-warnings",
    ),
    pytest.param(
        lambda mp: _containers(12, "paused"),
        "warning",
        f"Container warnings: {_first_ten(_PAUSED)} {_NOT_RUNNING}",
        id="docker-12-warnings",
    ),
    pytest.param(
        lambda mp: _containers(10, "dead"),
        "critical",
        f"Container problems: {', '.join(_DEAD[:10])} {_NOT_RUNNING}",
        id="docker-10-problems",
    ),
    # smart_health
    pytest.param(
        lambda mp: _smart_disks(0x10 | 0x20, 12),
        "critical",
        f"SMART problems: {_first_ten(_PREFAIL)}; warnings: {_first_ten(_PAST)}",
        id="smart-12-problems-and-warnings",
    ),
    pytest.param(
        lambda mp: _smart_disks(0x20, 12),
        "warning",
        f"SMART warnings: {_first_ten(_PAST)}",
        id="smart-12-warnings",
    ),
    pytest.param(
        lambda mp: _smart_disks(0x10, 10),
        "critical",
        "SMART problems: " + ", ".join(_PREFAIL[:10]),
        id="smart-10-problems",
    ),
    # agent_resources
    pytest.param(
        lambda mp: _full_disks(12),
        "critical",
        _first_ten(_DISKS_FULL, "; "),
        id="resources-12-problems",
    ),
    pytest.param(
        lambda mp: _full_disks(10),
        "critical",
        "; ".join(_DISKS_FULL[:10]),
        id="resources-10-problems",
    ),
    # service_process, auto mode
    pytest.param(
        lambda mp: _auto({"failed": _FAILED, "enabled_inactive": _INACTIVE}),
        "critical",
        f"Failed: {_first_ten(_FAILED)}; Inactive (autostart): {_first_ten(_INACTIVE)}",
        id="auto-12-failed-and-inactive",
    ),
    pytest.param(
        lambda mp: _auto({"failed": [], "enabled_inactive": _INACTIVE}),
        "warning",
        f"Inactive (autostart): {_first_ten(_INACTIVE)}",
        id="auto-12-inactive",
    ),
    pytest.param(
        lambda mp: _auto({"failed": _FAILED[:10], "enabled_inactive": []}),
        "critical",
        "Failed: " + ", ".join(_FAILED[:10]),
        id="auto-10-failed",
    ),
    pytest.param(
        lambda mp: _auto({"failed": _FAILED + _FAILED_UNITS, "enabled_inactive": _INACTIVE}),
        "critical",
        f"Failed: {_first_ten(_FAILED)}; Failed units: {_first_ten(_FAILED_UNITS)}; "
        f"Inactive (autostart): {_first_ten(_INACTIVE)}",
        id="auto-12-failed-12-failed-units-and-inactive",
    ),
    # service_process, list mode
    pytest.param(
        lambda mp: _listed(_DOWN + _NODATA, _watch(**dict.fromkeys(_DOWN, False))),
        "critical",
        f"Services not active: {_first_ten(_DOWN)}; no data: {_first_ten(_NODATA)}",
        id="list-12-down-and-no-data",
    ),
    pytest.param(
        lambda mp: _listed(_NODATA, {}),
        "unknown",
        f"Services without data: {_first_ten(_NODATA)}",
        id="list-12-no-data",
    ),
    pytest.param(
        lambda mp: _listed(_DOWN[:10], _watch(**dict.fromkeys(_DOWN[:10], False))),
        "critical",
        "Services not active: " + ", ".join(_DOWN[:10]),
        id="list-10-down",
    ),
    # disk_forecast
    pytest.param(
        lambda mp: _filling_mounts(mp, 12),
        "critical",
        _first_ten(_FILLING, "; "),
        id="forecast-12-problems",
    ),
    pytest.param(
        lambda mp: _filling_mounts(mp, 10),
        "critical",
        "; ".join(_FILLING[:10]),
        id="forecast-10-problems",
    ),
]


@pytest.mark.parametrize(("call", "status", "message"), LIST_CASES)
def test_list_in_message_names_at_most_ten_entries(monkeypatch, call, status, message):
    got_status, got_message, _ = call(monkeypatch)
    assert (got_status, got_message) == (status, message)


# --- text from the report in a message: one line, every control character a space ---
# The message goes unchanged into the dashboard, the bell, mail and webhook; a line break in
# a container name would put a forged line of its own into each of them.


def _one_line(text):
    """No character of Unicode category Cc and no line or paragraph separator."""
    return not any(unicodedata.category(c) == "Cc" or c in "\u2028\u2029" for c in text)


@pytest.mark.parametrize(
    "char",
    ["\n", "\r", "\t", "\x1b", "\x7f", "\x85", "\u2028", "\u2029"],
    ids=["lf", "cr", "tab", "esc", "del", "nel", "line-separator", "paragraph-separator"],
)
def test_cap_agent_text_turns_a_control_character_into_a_space(char):
    assert agent.cap_agent_text(f"a{char}b") == "a b"


def test_cap_agent_text_turns_every_control_character_into_a_space():
    controls = [chr(c) for c in range(0x110000) if unicodedata.category(chr(c)) == "Cc"]
    assert len(controls) == 65  # U+0000-U+001F and U+007F-U+009F
    text = "".join(controls) + "\u2028\u2029"
    assert agent.cap_agent_text(text) == " " * 67


def test_cap_agent_text_cuts_a_multiline_text_to_one_line_of_500_characters():
    text = "line\n" * 120  # 600 characters
    capped = agent.cap_agent_text(text)
    assert capped == ("line " * 120)[:499] + "…"
    assert len(capped) == 500
    assert _one_line(capped)


def test_cap_agent_text_keeps_a_text_without_control_characters():
    # U+00A0 is the first character after the C1 controls.
    assert agent.cap_agent_text("nginx-ä ß\u00a0x") == "nginx-ä ß\u00a0x"


class _RecordingText(str):
    """A report text that records the length of each translate call made on it."""

    def translate(self, table):
        self.translated.append(len(self))
        return super().translate(table)


def test_cap_agent_text_translates_at_most_500_characters():
    # Cutting first gives the same text (one character for one) and bounds the work however
    # long the report text is: what lies behind the cut is dropped, never translated.
    short, long = _RecordingText("a\n" * 250), _RecordingText("a\n" * 5000)
    short.translated, long.translated = [], []
    assert agent.cap_agent_text(short) == "a " * 250
    assert agent.cap_agent_text(long) == ("a " * 5000)[:499] + "…"
    assert short.translated == [500]  # the recorder sees a call on the text itself
    assert all(n <= 500 for n in long.translated)


def _docker(container):
    return DockerHealthChecker().evaluate({}, {"docker": {"containers": [container]}})


def _outage(key, error, error_message):
    block = {"available": False, "error": error, "error_message": error_message}
    checker = ZfsHealthChecker() if key == "zfs" else DockerHealthChecker()
    return checker.evaluate({}, {key: block})


def _smart_model(model):
    disk = {
        "device": "/dev/sda",
        "model": model,
        "protocol": "ATA",
        "kind": "HDD",
        "temp_c": 30,
        "smartctl_status": 0x10,
    }
    return SmartHealthChecker().evaluate({}, {"smart": [disk]})


def _pool(name, health):
    pool = {"name": name, "health": health, "capacity_percent": 10}
    return ZfsHealthChecker().evaluate({}, {"zfs": {"pools": [pool]}})


# Each place that copies a text from the report into a message, with a line break in it: each
# control character becomes one space, so "\r\n" makes two; status and the rest stay.
MULTILINE_CASES = [
    pytest.param(
        lambda: _docker({"id": "c1", "name": "web\nStatus: ok -> ok", "state": "dead"}),
        "critical",
        "Container problems: web Status: ok -> ok: dead (0 running, 0 stopped)",
        id="docker-name",
    ),
    pytest.param(
        lambda: _pool("p\r\nq", "DEGRADED"),
        "critical",
        "p  q: DEGRADED",
        id="zfs-pool-name",
    ),
    pytest.param(
        lambda: _smart_model("X\u2028Y"),
        "critical",
        "SMART problems: /dev/sda (X Y): prefail attribute below threshold (smartctl 0x10)",
        id="smart-model",
    ),
    pytest.param(
        lambda: _proxmox(_vm(101, "qemu", "a\x85b", None)),
        "critical",
        "No backup: QEMU 101 (a b)",
        id="proxmox-vm-name",
    ),
    pytest.param(
        lambda: _auto({"failed": ["a\nb.service"], "enabled_inactive": ["c\u2029d.service"]}),
        "critical",
        "Failed: a b.service; Inactive (autostart): c d.service",
        id="service-process-failed",
    ),
    pytest.param(
        lambda: _auto({"failed": ["a\nb.mount"], "enabled_inactive": []}),
        "warning",
        "Failed units: a b.mount",
        id="service-process-failed-unit",
    ),
    pytest.param(
        lambda: _outage("zfs", "timeout", "zpool\nlist timed out"),
        "warning",
        "ZFS unavailable (timeout): zpool list timed out",
        id="zfs-error-message",
    ),
    pytest.param(
        lambda: _outage("docker", "daemon_unreachable", "docker info\r\nfailed"),
        "warning",
        "Docker unavailable (daemon_unreachable): docker info  failed",
        id="docker-error-message",
    ),
    pytest.param(
        lambda: _auto({"failed": [], "enabled_inactive": [], "error": "list-units\nfailed"}),
        "unknown",
        "Services not queryable: list-units failed",
        id="systemd-error",
    ),
    pytest.param(
        lambda: _resources({"resources": {"disks": [{"mount": "/m\x1b[2J", "percent": 95}]}}),
        "critical",
        "Disk /m [2J 95% (>=95%)",
        id="resources-mount",
    ),
]


@pytest.mark.parametrize(("call", "status", "message"), MULTILINE_CASES)
def test_report_text_in_message_is_one_line(call, status, message):
    got_status, got_message, _ = call()
    assert (got_status, got_message) == (status, message)
    assert _one_line(got_message)


def test_docker_name_and_state_in_details_are_one_line():
    # The rating reads the full state: "dead\n" is no known state.
    _, _, metrics = _docker({"id": "c1", "name": "web\nStatus: ok", "state": "Dead\n"})
    container = metrics["_details"]["containers"][0]
    assert (container["name"], container["state"]) == ("web Status: ok", "dead ")
    assert container["reason"] == "unknown_state"


# --- check engine: what it writes into MonitorState.message itself ---


class _AddOnlyDb:
    """apply_result only calls db.add() on the create path."""

    def add(self, obj):
        pass


def test_damping_suffix_is_english():
    check = MonitorCheck(id="c1", name="c1", check_type="ping", config="{}", consecutive_fails=2)
    state = MonitorState(check_id="c1", status="ok", fail_count=0)
    ce.apply_result(_AddOnlyDb(), check, state, "critical", "down", None, utcnow_naive())
    assert (state.status, state.message) == ("ok", "down (failure 1/2)")


class _Boom:
    def run(self, config):
        raise RuntimeError("boom")


@pytest.mark.parametrize(
    ("check_type", "config", "checker", "message"),
    [
        pytest.param("ping", "{not json", None, "Invalid check configuration", id="bad-config"),
        pytest.param("no_such_type", "{}", None, "Unknown check type", id="unknown-type"),
        pytest.param("ping", "{}", _Boom(), "Unexpected error: boom", id="checker-raises"),
    ],
)
def test_engine_message_is_english(monkeypatch, check_type, config, checker, message):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                name="c1",
                check_type=check_type,
                config=config,
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(ce.victoria, "write_check_result", lambda **kw: None)
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: None))
    if checker is not None:
        monkeypatch.setattr(ce, "get_checker", lambda _check_type: checker)

    ce.execute_check("c1")

    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="c1").one()
        assert (state.status, state.message) == ("unknown", message)


def test_get_checker_unknown_type_error_is_english():
    # The text only reaches the engine's log line; the state message is the case above.
    with pytest.raises(ValueError) as exc_info:
        get_checker("no_such_type")
    assert str(exc_info.value) == "Unknown check_type: 'no_such_type'"
