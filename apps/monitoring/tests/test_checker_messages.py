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
from app.checkers import http as http_mod
from app.checkers import ping as ping_mod
from app.checkers import tcp as tcp_mod
from app.checkers.agent import AgentPingChecker, AgentResourcesChecker, ServiceProcessChecker
from app.checkers.plugins import DockerHealthChecker, ProxmoxBackupChecker, ZfsHealthChecker
from app.checkers.smart import SmartHealthChecker
from app.core.ssrf import UrlVerdict
from app.core.time import utcnow_naive
from app.models import Base, MonitorCheck, MonitorState

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


# --- pull checkers: the network is faked in each case ---

# A public IP literal: the SSRF guard lets it through without DNS.
_PUBLIC = "http://93.184.216.34/"


def _reply(status_code, text="", location=None):
    headers = {"location": location} if location else {}

    def respond(method, url, **kwargs):
        return httpx.Response(
            status_code, text=text, headers=headers, request=httpx.Request(method, url)
        )

    return respond


def _raise(exc):
    def respond(*args, **kwargs):
        raise exc

    return respond


def _http(mp, respond, **config):
    mp.setattr(http_mod.httpx, "request", respond)
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
    mp.setattr(http_mod, "classify_url", lambda url: UrlVerdict.PRIVATE)
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
