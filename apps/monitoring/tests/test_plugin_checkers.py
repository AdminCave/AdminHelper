# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Alert-decision logic of the plugin checkers (Proxmox/ZFS/Docker). These produce field false
alarms or swallowed alarms if they drift — e.g. a regression dropping DEGRADED from the critical set
would never be noticed without a test (6.53)."""

import pytest

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
def _ctr(**fields):
    """One container as the agent reports it since R-0419 (inspect fields included)."""
    c = {
        "id": "abc123def456",
        "name": "web",
        "image": "nginx:1.27",
        "state": "running",
        "status": "Up 2 hours",
        "restart_policy": "no",
        "exit_code": 0,
        "oom_killed": False,
        "restart_count": 0,
        "health": "",
    }
    c.update(fields)
    return c


def _docker(*containers, **block):
    return {"docker": {"available": True, "error": None, "containers": list(containers), **block}}


def _rows(metrics):
    return metrics["_details"]["containers"]


# One case per row of the spec table "Bewertung je Container"
# (docs/features/monitoring-silent-outages.md); stopped counts as ok for the check.
# Kevin 2026-10-17: exit 143/137 without OOM is a stop, a created container with an
# exit code a failed start.
@pytest.mark.parametrize(
    ("fields", "status", "category", "reason"),
    [
        ({"health": "unhealthy"}, "warning", "warning", "unhealthy"),
        ({"health": "healthy"}, "ok", "ok", None),
        ({"health": "starting"}, "ok", "ok", None),
        ({}, "ok", "ok", None),
        (
            {"state": "restarting", "restart_policy": "always", "exit_code": 1},
            "critical",
            "critical",
            "restarting",
        ),
        ({"state": "dead"}, "critical", "critical", "dead"),
        ({"state": "paused"}, "warning", "warning", "paused"),
        ({"state": "created"}, "ok", "stopped", "created"),
        ({"state": "created", "exit_code": 127}, "critical", "critical", "start_failed"),
        ({"state": "exited", "exit_code": 137, "oom_killed": True}, "critical", "critical", "oom"),
        (
            {"state": "exited", "exit_code": 137, "oom_killed": True, "restart_policy": "always"},
            "critical",
            "critical",
            "oom",
        ),
        ({"state": "exited", "restart_policy": "always"}, "ok", "stopped", "stopped"),
        (
            {"state": "exited", "exit_code": 143, "restart_policy": "always"},
            "ok",
            "stopped",
            "stopped",
        ),
        (
            {"state": "exited", "exit_code": 2, "restart_policy": "unless-stopped"},
            "ok",
            "stopped",
            "stopped",
        ),
        (
            {"state": "exited", "exit_code": 1, "restart_policy": "on-failure"},
            "critical",
            "critical",
            "exit:1",
        ),
        ({"state": "exited", "restart_policy": "on-failure"}, "ok", "stopped", "stopped"),
        ({"state": "exited", "exit_code": 3}, "critical", "critical", "exit:3"),
        ({"state": "exited", "exit_code": 139}, "critical", "critical", "exit:139"),
        ({"state": "exited", "exit_code": 143}, "ok", "stopped", "stopped"),
        ({"state": "exited", "exit_code": 137}, "ok", "stopped", "stopped"),
        (
            {"state": "exited", "exit_code": 143, "restart_policy": "on-failure"},
            "ok",
            "stopped",
            "stopped",
        ),
        (
            {"state": "exited", "exit_code": 3, "restart_policy": ""},
            "critical",
            "critical",
            "exit:3",
        ),
        ({"state": "exited"}, "ok", "stopped", "stopped"),
    ],
    ids=[
        "running-unhealthy",
        "running-healthy",
        "running-health-starting",
        "running",
        "restarting",
        "dead",
        "paused",
        "created",
        "created-start-failed",
        "exited-oom",
        "exited-oom-always",
        "exited-always-stopped-by-hand",
        "exited-always-sigterm-exit",
        "exited-unless-stopped",
        "exited-on-failure-retries-exhausted",
        "exited-on-failure-exit-0",
        "exited-3-no-policy",
        "exited-139-segfault",
        "exited-143-sigterm",
        "exited-137-sigkill-after-timeout",
        "exited-143-on-failure",
        "exited-3-empty-policy",
        "exited-0-no-policy",
    ],
)
def test_docker_container_rating_follows_spec_table(fields, status, category, reason):
    got_status, _, metrics = DockerHealthChecker().evaluate({}, _docker(_ctr(**fields)))
    assert got_status == status
    [row] = _rows(metrics)
    assert (row["category"], row["reason"]) == (category, reason)


# Docker 29.8.1 (API 1.56), probed 2026-10-17 with alpine containers: State.Status,
# ExitCode and OOMKilled as docker inspect showed them, Status as docker ps did.
# State.Error (not reported by the agent) held the runc message for the failed start
# and was empty for all others.
@pytest.mark.parametrize(
    ("container", "category", "reason"),
    [
        # docker run alpine /nonexistent-cmd: the first start fails, the container stays created
        (_ctr(state="created", status="Created", exit_code=127), "critical", "start_failed"),
        # docker create, never started
        (_ctr(state="created", status="Created", exit_code=0), "stopped", "created"),
        # docker run --init alpine sleep 1000; docker stop: tini forwards TERM -> 128+15
        (
            _ctr(state="exited", status="Exited (143) 17 seconds ago", exit_code=143),
            "stopped",
            "stopped",
        ),
        # docker run alpine sleep 1000 (PID 1 ignores TERM); docker stop kills it after 10 s
        (
            _ctr(state="exited", status="Exited (137) 7 seconds ago", exit_code=137),
            "stopped",
            "stopped",
        ),
        # docker run --restart always --init alpine sleep 1000; docker stop
        (
            _ctr(
                state="exited",
                status="Exited (143) 6 seconds ago",
                exit_code=143,
                restart_policy="always",
            ),
            "stopped",
            "stopped",
        ),
        # docker run alpine sh -c 'exit 3'
        (
            _ctr(state="exited", status="Exited (3) 19 seconds ago", exit_code=3),
            "critical",
            "exit:3",
        ),
    ],
    ids=["failed-start", "never-started", "sigterm", "sigkill", "always-sigterm", "exit-3"],
)
def test_docker_29_probe_containers(container, category, reason):
    _, _, metrics = DockerHealthChecker().evaluate({}, _docker(container))
    [row] = _rows(metrics)
    assert (row["category"], row["reason"]) == (category, reason)


def test_docker_detail_row_carries_id_exit_code_and_restart_count():
    _, _, metrics = DockerHealthChecker().evaluate(
        {}, _docker(_ctr(name="db", state="exited", exit_code=3, restart_count=4))
    )
    assert metrics["_details"]["available"] is True
    assert metrics["_details"]["error"] is None
    assert _rows(metrics) == [
        {
            "id": "abc123def456",
            "name": "db",
            "image": "nginx:1.27",
            "state": "exited",
            "category": "critical",
            "reason": "exit:3",
            "exit_code": 3,
            "restart_count": 4,
        }
    ]


def test_docker_rising_restart_count_is_warning():
    prev = {"containers": [{"id": "abc123def456", "restart_count": 2}]}
    status, msg, metrics = DockerHealthChecker().evaluate({}, _docker(_ctr(restart_count=3)), prev)
    assert status == "warning"
    assert "web" in msg and "restarted" in msg
    [row] = _rows(metrics)
    assert (row["category"], row["reason"], row["restart_count"]) == ("warning", "restarted", 3)


@pytest.mark.parametrize(
    "prev",
    [
        None,  # first evaluation, nothing to compare
        {"containers": [{"id": "abc123def456", "restart_count": 3}]},  # unchanged
        {"containers": [{"id": "abc123def456", "restart_count": 5}]},  # reset by a manual start
        {"containers": [{"id": "ffffffffffff", "restart_count": 0}]},  # another container
        {"containers": [{"name": "web", "state": "running", "category": "ok"}]},  # pre-R-0419
        {"available": False, "error": "timeout", "containers": []},  # last push unavailable
    ],
    ids=["no-prev", "unchanged", "reset", "other-id", "old-details", "prev-unavailable"],
)
def test_docker_restart_count_without_rise_stays_ok(prev):
    status, _, _ = DockerHealthChecker().evaluate({}, _docker(_ctr(restart_count=3)), prev)
    assert status == "ok"


def test_docker_unhealthy_wins_over_restart_as_reason():
    prev = {"containers": [{"id": "abc123def456", "restart_count": 0}]}
    _, _, metrics = DockerHealthChecker().evaluate(
        {}, _docker(_ctr(health="unhealthy", restart_count=1)), prev
    )
    assert _rows(metrics)[0]["reason"] == "unhealthy"


@pytest.mark.parametrize("code", ["daemon_unreachable", "timeout", "cli_failed", "parse_failed"])
def test_docker_unavailable_is_warning_without_containers(code):
    report = _docker(
        _ctr(name="stale"), available=False, error=code, error_message="docker info failed"
    )
    status, msg, metrics = DockerHealthChecker().evaluate({}, report)
    assert status == "warning"
    assert code in msg and "docker info failed" in msg
    assert metrics == {"_details": {"available": False, "error": code, "containers": []}}


def test_docker_error_with_available_true_is_still_unavailable():
    status, _, metrics = DockerHealthChecker().evaluate({}, _docker(error="parse_failed"))
    assert status == "warning"
    assert metrics["_details"] == {"available": False, "error": "parse_failed", "containers": []}


def test_docker_unavailable_with_alert_off_is_unknown_with_same_message():
    report = _docker(
        available=False, error="daemon_unreachable", error_message="docker info failed"
    )
    _, warn_msg, warn_metrics = DockerHealthChecker().evaluate({}, report)
    status, msg, metrics = DockerHealthChecker().evaluate({"alert_on_unavailable": False}, report)
    assert status == "unknown"
    assert msg == warn_msg
    assert metrics == warn_metrics


def test_docker_unavailable_alert_is_only_off_for_a_real_false():
    # StrictBool keeps strings out on the API path; should one slip through, "false" is
    # truthy and must not silence the alert.
    report = _docker(available=False, error="timeout")
    status, _, _ = DockerHealthChecker().evaluate({"alert_on_unavailable": "false"}, report)
    assert status == "warning"


def test_docker_block_missing_is_unknown_and_clears_containers():
    status, _, metrics = DockerHealthChecker().evaluate({}, {"resources": {}})
    assert status == "unknown"
    # Details, not None: the push path keeps stored details when a result has none,
    # and the desktop would go on showing the last container list.
    assert metrics == {"_details": {"containers": []}}


def test_docker_zero_containers_is_ok_with_empty_list():
    status, _, metrics = DockerHealthChecker().evaluate({}, _docker())
    assert status == "ok"
    assert metrics["_details"] == {"available": True, "error": None, "containers": []}


def test_docker_message_counts_running_stopped_and_problems():
    report = _docker(
        _ctr(id="000000000001", name="web"),
        _ctr(id="000000000002", name="api", health="unhealthy"),
        _ctr(id="000000000003", name="db", state="exited", exit_code=3),
        _ctr(id="000000000004", name="job", state="exited"),
        _ctr(id="000000000005", name="init", state="created"),
        _ctr(id="000000000006", name="cache", state="exited", exit_code=137, oom_killed=True),
        _ctr(id="000000000007", name="boot", state="created", exit_code=127),
    )
    status, msg, metrics = DockerHealthChecker().evaluate({}, report)
    assert status == "critical"
    assert "db: exited with code 3" in msg and "cache: OOM-killed" in msg
    assert "boot: failed to start" in msg
    assert "api: unhealthy" in msg
    assert "2 running, 2 stopped" in msg
    assert "web" not in msg and "job" not in msg
    assert (metrics["docker_ok"], metrics["docker_warning"], metrics["docker_critical"]) == (
        1,
        1,
        3,
    )


def test_docker_message_ok_names_stopped_containers_apart():
    report = _docker(
        _ctr(id="000000000001", name="web"),
        _ctr(id="000000000002", name="job", state="exited"),
    )
    status, msg, _ = DockerHealthChecker().evaluate({}, report)
    assert (status, msg) == ("ok", "1 running, 1 stopped")


def test_docker_message_all_running():
    report = _docker(_ctr(id="000000000001", name="web"), _ctr(id="000000000002", name="api"))
    status, msg, _ = DockerHealthChecker().evaluate({}, report)
    assert (status, msg) == ("ok", "All 2 containers running")


def test_docker_removing_counts_as_stopped():
    # Not in the spec table: `docker rm` of a stopped container, an operator action.
    status, _, metrics = DockerHealthChecker().evaluate({}, _docker(_ctr(state="removing")))
    assert status == "ok"
    assert (_rows(metrics)[0]["category"], _rows(metrics)[0]["reason"]) == ("stopped", "stopped")


def test_docker_unknown_state_is_warning():
    # Not in the spec table: a state Docker does not document is surfaced, not rated ok.
    status, _, metrics = DockerHealthChecker().evaluate({}, _docker(_ctr(state="frozen")))
    assert status == "warning"
    assert _rows(metrics)[0]["reason"] == "unknown_state"


@pytest.mark.parametrize(
    ("status_text", "status", "reason"),
    [
        ("Exited (3) 2 minutes ago", "critical", "exit:3"),
        ("Exited (0) 1 hour ago", "ok", "stopped"),
        ("Exited (137) 7 seconds ago", "ok", "stopped"),
    ],
)
def test_docker_old_agent_exit_code_from_status_text(status_text, status, reason):
    # Agents before R-0419 send no exit_code; docker ps prints it in the status text.
    c = _ctr(state="exited", status=status_text)
    del c["exit_code"]
    got, _, metrics = DockerHealthChecker().evaluate({}, _docker(c))
    assert got == status
    assert _rows(metrics)[0]["reason"] == reason


def test_docker_unhealthy_is_warning():
    # Agent before R-0419: no health field, the ps status text carries it.
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
    r = _docker(_ctr(name="watchtower", state="exited", exit_code=1))
    assert DockerHealthChecker().evaluate({}, r)[0] == "critical"  # rated when not ignored
    status, _, metrics = DockerHealthChecker().evaluate({"ignore_containers": ["watchtower"]}, r)
    assert status == "ok"  # the only problem container is ignored
    assert _rows(metrics) == []
