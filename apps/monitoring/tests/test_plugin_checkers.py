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


def _zfs(*pools, **block):
    """The zfs block as the agent reports it since R-0419 (available/error always set)."""
    return {"zfs": {"available": True, "error": None, "pools": list(pools), **block}}


def _pool(name="tank", health="ONLINE", capacity_percent=20):
    return {"name": name, "health": health, "capacity_percent": capacity_percent}


def test_zfs_healthy_pools_stay_ok_and_details_carry_available():
    status, msg, metrics = ZfsHealthChecker().evaluate(
        {}, _zfs(_pool(), _pool("backup", capacity_percent=55))
    )
    assert status == "ok"
    assert msg == "All pools ONLINE: tank 20%, backup 55%"
    assert metrics["zfs_capacity_tank"] == 20 and metrics["zfs_capacity_backup"] == 55
    assert metrics["_details"] == {
        "available": True,
        "error": None,
        "pools": [
            {"name": "tank", "health": "ONLINE", "capacityPercent": 20},
            {"name": "backup", "health": "ONLINE", "capacityPercent": 55},
        ],
    }


def test_zfs_old_agent_block_without_available_is_rated_as_before():
    # Agents before R-0419 send the block only after a good zpool list, without available.
    report = {"zfs": {"pools": [_pool(health="DEGRADED")]}}
    status, msg, metrics = ZfsHealthChecker().evaluate({}, report)
    assert status == "critical" and msg == "tank: DEGRADED"
    assert metrics["_details"]["available"] is True


@pytest.mark.parametrize("code", ["timeout", "cli_failed"])
def test_zfs_unavailable_is_warning_without_pools(code):
    report = _zfs(
        _pool(name="stale"), available=False, error=code, error_message="zpool list timed out"
    )
    status, msg, metrics = ZfsHealthChecker().evaluate({}, report)
    assert status == "warning"
    assert code in msg and "zpool list timed out" in msg
    assert metrics == {"_details": {"available": False, "error": code, "pools": []}}


def test_zfs_error_with_available_true_is_still_unavailable():
    status, _, metrics = ZfsHealthChecker().evaluate({}, _zfs(error="cli_failed"))
    assert status == "warning"
    assert metrics["_details"] == {"available": False, "error": "cli_failed", "pools": []}


def test_zfs_unavailable_with_alert_off_is_unknown_with_same_message():
    report = _zfs(available=False, error="timeout", error_message="zpool list timed out")
    _, warn_msg, warn_metrics = ZfsHealthChecker().evaluate({}, report)
    status, msg, metrics = ZfsHealthChecker().evaluate({"alert_on_unavailable": False}, report)
    assert status == "unknown"
    assert msg == warn_msg
    assert metrics == warn_metrics


def test_zfs_unavailable_alert_is_only_off_for_a_real_false():
    report = _zfs(available=False, error="timeout")
    status, _, _ = ZfsHealthChecker().evaluate({"alert_on_unavailable": "false"}, report)
    assert status == "warning"


def test_zfs_block_missing_is_unknown_and_clears_pools():
    status, _, metrics = ZfsHealthChecker().evaluate({}, {"resources": {}})
    assert status == "unknown"
    # Details, not None: the push path keeps stored details when a result has none.
    assert metrics == {"_details": {"pools": []}}


def test_zfs_zero_pools_is_ok_with_empty_list():
    status, _, metrics = ZfsHealthChecker().evaluate({}, _zfs())
    assert status == "ok"
    assert metrics == {"_details": {"available": True, "error": None, "pools": []}}


def test_zfs_caps_the_pool_list():
    # Like the containers, only the first 500 pools are rated, so a broken agent cannot
    # flood the details and the message (R-0486).
    names = [f"p{i}" for i in range(2000)]
    status, msg, metrics = ZfsHealthChecker().evaluate({}, _zfs(*(_pool(name=n) for n in names)))
    assert status == "ok"
    assert msg == "All pools ONLINE: " + ", ".join(f"{n} 20%" for n in names[:500])
    assert [p["name"] for p in metrics["_details"]["pools"]] == names[:500]
    assert sum(k.startswith("zfs_capacity_") for k in metrics) == 500


@pytest.mark.parametrize("pools", ["abc", {"name": "tank"}, 42], ids=["str", "dict", "int"])
def test_zfs_pools_that_are_no_list_count_as_empty(pools):
    status, msg, metrics = ZfsHealthChecker().evaluate({}, _zfs(pools=pools))
    assert (status, msg) == ("ok", "No ZFS pools found")
    assert metrics == {"_details": {"available": True, "error": None, "pools": []}}


def test_zfs_pool_that_is_no_object_is_skipped():
    status, msg, metrics = ZfsHealthChecker().evaluate({}, _zfs("x", _pool(health="DEGRADED")))
    assert (status, msg) == ("critical", "tank: DEGRADED")
    assert metrics["_details"]["pools"] == [
        {"name": "tank", "health": "DEGRADED", "capacityPercent": 20}
    ]


def test_zfs_pool_without_name_is_named_by_a_question_mark():
    pool = _pool()
    del pool["name"]
    status, msg, _ = ZfsHealthChecker().evaluate({}, _zfs(pool))
    assert (status, msg) == ("ok", "All pools ONLINE: ? 20%")


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


@pytest.mark.parametrize(("stored", "expected"), [(0, "ok"), ("false", "ok"), (False, "critical")])
def test_proxmox_exclude_stopped_off_only_for_real_false(stored, expected):
    # R-0456: a stored non-bool (from before the strict boundary) counts as the
    # default, as the check editor shows it; only a real False includes stopped VMs.
    r = {"proxmox": {"vms": [{"vmid": 101, "status": "stopped", "last_backup_ts": None}]}}
    status, _, _ = ProxmoxBackupChecker().evaluate({"exclude_stopped": stored}, r)
    assert status == expected


def test_proxmox_caps_the_vm_list(monkeypatch):
    monkeypatch.setattr("app.checkers.plugins.time.time", lambda: 1_000_000.0)
    vms = [{"vmid": i, "status": "running", "last_backup_ts": 1_000_000.0} for i in range(2000)]
    status, msg, metrics = ProxmoxBackupChecker().evaluate({}, {"proxmox": {"vms": vms}})
    assert (status, msg) == ("ok", "All 500 VMs/CTs have up-to-date backups")
    assert [vm["vmid"] for vm in metrics["_details"]["vms"]] == list(range(500))
    assert metrics["proxmox_backup_ok"] == 500


@pytest.mark.parametrize("vms", ["abc", {"vmid": 100}, 42], ids=["str", "dict", "int"])
def test_proxmox_vms_that_are_no_list_count_as_empty(vms):
    result = ProxmoxBackupChecker().evaluate({}, {"proxmox": {"vms": vms}})
    assert result == ("ok", "No VMs/CTs found", None)


def test_proxmox_vm_that_is_no_object_is_skipped():
    r = {"proxmox": {"vms": ["x", {"vmid": 100, "status": "running", "last_backup_ts": None}]}}
    status, msg, metrics = ProxmoxBackupChecker().evaluate({}, r)
    assert (status, msg) == ("critical", "No backup: VM 100 (?)")
    assert [vm["vmid"] for vm in metrics["_details"]["vms"]] == [100]


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


def test_docker_previous_values_skip_malformed_entries():
    # A malformed entry must not make evaluate raise (the push path then drops the check and
    # its state stands still); the valid previous value still counts (R-0459).
    prev = {
        "containers": [
            {"id": ["a"]},
            "no-dict",
            {"id": "abc123def456", "restart_count": 1},
        ]
    }
    status, _, metrics = DockerHealthChecker().evaluate({}, _docker(_ctr(restart_count=2)), prev)
    assert status == "warning"
    assert _rows(metrics)[0]["reason"] == "restarted"

    # A containers value that is no list has no previous values.
    status, _, _ = DockerHealthChecker().evaluate(
        {}, _docker(_ctr(restart_count=2)), {"containers": 42}
    )
    assert status == "ok"


def test_docker_container_id_that_is_no_string_has_no_previous_value():
    prev = {"containers": [{"id": "abc123def456", "restart_count": 0}]}
    status, _, metrics = DockerHealthChecker().evaluate(
        {}, _docker(_ctr(id=["abc123def456"], restart_count=3)), prev
    )
    assert status == "ok"
    assert _rows(metrics)[0]["reason"] is None


def test_docker_container_without_name_falls_back_to_a_string_id_only():
    c = _ctr()
    del c["name"]
    _, _, metrics = DockerHealthChecker().evaluate({}, _docker(c))
    assert _rows(metrics)[0]["name"] == "abc123def456"

    # Any other ID gives the neutral "?" instead of failing at the ignore lookup.
    c["id"] = ["abc123def456"]
    status, _, metrics = DockerHealthChecker().evaluate({"ignore_containers": ["db"]}, _docker(c))
    assert status == "ok"
    assert _rows(metrics)[0]["name"] == "?"


# A broken or taken-over agent sends name, state and status of any JSON type (R-0507);
# only a string counts, anything else is treated like a missing or empty field.
@pytest.mark.parametrize("name", [["web"], {"web": 1}, 42], ids=["list", "dict", "int"])
def test_docker_name_that_is_no_string_falls_back_to_the_id(name):
    status, _, metrics = DockerHealthChecker().evaluate(
        {"ignore_containers": ["db"]}, _docker(_ctr(name=name))
    )
    assert status == "ok"
    assert _rows(metrics)[0]["name"] == "abc123def456"


def test_docker_state_that_is_no_string_is_unknown_state():
    status, msg, metrics = DockerHealthChecker().evaluate({}, _docker(_ctr(state=5)))
    assert status == "warning"
    assert msg == "Container warnings: web: unknown state '' (0 running, 0 stopped)"
    assert (_rows(metrics)[0]["state"], _rows(metrics)[0]["reason"]) == ("", "unknown_state")


def test_docker_old_agent_status_text_that_is_no_string_has_no_exit_code():
    c = _ctr(state="exited", status=5)
    del c["exit_code"]
    status, _, metrics = DockerHealthChecker().evaluate({}, _docker(c))
    assert status == "ok"
    row = _rows(metrics)[0]
    assert (row["category"], row["reason"], row["exit_code"]) == ("stopped", "stopped", None)


def test_docker_old_agent_status_text_that_is_no_string_is_not_unhealthy():
    c = _ctr(status=5)
    del c["health"]
    status, _, metrics = DockerHealthChecker().evaluate({}, _docker(c))
    assert status == "ok"
    assert (_rows(metrics)[0]["category"], _rows(metrics)[0]["reason"]) == ("ok", None)


# Name and state go into MonitorState.message, webhook and mail unchanged: only 500 characters
# of each, the ellipsis included, reach message and details (R-0508).
def test_docker_long_name_is_capped_in_message_and_details():
    status, msg, metrics = DockerHealthChecker().evaluate(
        {}, _docker(_ctr(name="n" * 10_000, state="dead"))
    )
    name = "n" * 499 + "…"
    assert status == "critical"
    assert msg == f"Container problems: {name}: dead (0 running, 0 stopped)"
    assert _rows(metrics)[0]["name"] == name


def test_docker_long_state_is_capped_in_message_and_details():
    status, msg, metrics = DockerHealthChecker().evaluate({}, _docker(_ctr(state="s" * 10_000)))
    state = "s" * 499 + "…"
    assert status == "warning"
    assert msg == f"Container warnings: web: unknown state {state!r} (0 running, 0 stopped)"
    assert (_rows(metrics)[0]["state"], _rows(metrics)[0]["reason"]) == (state, "unknown_state")


def test_docker_ignore_compares_the_full_long_name():
    name = "i" * 600
    status, _, metrics = DockerHealthChecker().evaluate(
        {"ignore_containers": [name]}, _docker(_ctr(name=name, state="exited", exit_code=1))
    )
    assert status == "ok"
    assert _rows(metrics) == []


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


def test_docker_caps_the_container_list():
    # Like the router's per-report arrays, only the first 500 containers are rated, so a
    # broken agent cannot flood the details and the message (R-0459).
    ids = [f"{i:012x}" for i in range(2000)]
    report = _docker(*(_ctr(id=cid, name=f"c{cid}") for cid in ids))
    status, _, metrics = DockerHealthChecker().evaluate({}, report)
    assert status == "ok"
    assert [row["id"] for row in _rows(metrics)] == ids[:500]
    assert metrics["docker_ok"] == 500


@pytest.mark.parametrize(
    "containers", ["abc", {"id": "abc123def456"}, 42], ids=["str", "dict", "int"]
)
def test_docker_containers_that_are_no_list_count_as_empty(containers):
    status, msg, metrics = DockerHealthChecker().evaluate({}, _docker(containers=containers))
    assert (status, msg) == ("ok", "No containers found")
    assert metrics["_details"] == {"available": True, "error": None, "containers": []}


def test_docker_container_that_is_no_object_is_skipped():
    status, msg, metrics = DockerHealthChecker().evaluate({}, _docker("x", _ctr()))
    assert (status, msg) == ("ok", "All 1 containers running")
    assert [row["id"] for row in _rows(metrics)] == ["abc123def456"]


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


# --- Outage branch of ZfsHealthChecker and DockerHealthChecker (R-0472) ---
# Only the agent's codes and a capped error_message reach the message, which goes unchanged
# into MonitorState.message, webhook and mail; available is down only as a JSON false.
def _outage_case(kind, **block):
    """(checker, report with one healthy pool or container, message prefix, list key)."""
    if kind == "zfs":
        return ZfsHealthChecker(), _zfs(_pool(), **block), "ZFS unavailable", "pools"
    return DockerHealthChecker(), _docker(_ctr(), **block), "Docker unavailable", "containers"


@pytest.mark.parametrize(
    ("kind", "error"),
    [
        ("zfs", "disk_full"),
        ("zfs", "x" * 300),
        ("zfs", "daemon_unreachable"),
        ("zfs", ["timeout"]),
        ("docker", "disk_full"),
        ("docker", "x" * 300),
        ("docker", ["timeout"]),
    ],
    ids=[
        "zfs-disk_full",
        "zfs-300-chars",
        "zfs-docker-code",
        "zfs-list",
        "docker-disk_full",
        "docker-300-chars",
        "docker-list",
    ],
)
def test_unknown_error_code_is_an_outage_without_code(kind, error):
    checker, report, prefix, key = _outage_case(kind, available=False, error=error)
    status, msg, metrics = checker.evaluate({}, report)
    assert status == "warning"
    assert msg == prefix
    assert metrics == {"_details": {"available": False, "error": None, key: []}}


@pytest.mark.parametrize("kind", ["zfs", "docker"])
def test_error_message_is_capped(kind):
    checker, report, prefix, _ = _outage_case(
        kind, available=False, error="timeout", error_message="y" * 10_000
    )
    _, msg, _ = checker.evaluate({}, report)
    # 500 characters of agent text, the ellipsis included.
    assert msg == f"{prefix} (timeout): " + "y" * 499 + "…"


@pytest.mark.parametrize("kind", ["zfs", "docker"])
@pytest.mark.parametrize("error_message", [42, ["zpool list failed"]], ids=["int", "list"])
def test_error_message_that_is_no_string_is_left_out(kind, error_message):
    checker, report, prefix, _ = _outage_case(
        kind, available=False, error="timeout", error_message=error_message
    )
    status, msg, _ = checker.evaluate({}, report)
    assert status == "warning"
    assert msg == f"{prefix} (timeout)"


@pytest.mark.parametrize("kind", ["zfs", "docker"])
@pytest.mark.parametrize("available", ["false", 0, None], ids=["str-false", "zero", "null"])
def test_available_is_down_only_as_a_real_false(kind, available):
    checker, healthy, _, _ = _outage_case(kind, available=True)
    checker, report, _, _ = _outage_case(kind, available=available)
    assert checker.evaluate({}, report) == checker.evaluate({}, healthy)
    assert checker.evaluate({}, report)[0] == "ok"


# --- Malformed blocks and lists from a broken agent (R-0486) ---
_PLUGIN_CHECKERS = {
    "proxmox": ProxmoxBackupChecker,
    "zfs": ZfsHealthChecker,
    "docker": DockerHealthChecker,
}


@pytest.mark.parametrize("block", [[{}], "x", 1], ids=["list", "str", "int"])
@pytest.mark.parametrize("kind", ["proxmox", "zfs", "docker"])
def test_plugin_block_that_is_no_object_counts_as_missing(kind, block):
    checker = _PLUGIN_CHECKERS[kind]()
    result = checker.evaluate({}, {kind: block})
    assert result == checker.evaluate({}, {"resources": {}})
    assert result[0] == "unknown"


def test_plugin_list_is_capped_before_entries_that_are_no_object_are_skipped():
    # The cap bounds the work on a flooded list, so it counts every entry: a valid
    # container behind 500 junk entries is not rated.
    report = _docker(*(["x"] * 500), _ctr())
    assert DockerHealthChecker().evaluate({}, report)[:2] == ("ok", "No containers found")
