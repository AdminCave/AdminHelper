# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Plugin-based checkers.

Evaluate agent push data from automatically detected plugins
(Proxmox, ZFS, Docker). The data comes from the adminhelper-agent,
which activates the plugins based on installed binaries.
"""

from __future__ import annotations

import re
import time

from app.checkers.agent import agent_number, cap_agent_text, capped_objects, join_capped

# The codes the agent sends for a block it could not read (dockerUnavailable,
# zfsUnavailable and proxmoxUnavailable in apps/agent/internal/monitor/plugins.go).
_ZFS_ERRORS = frozenset({"timeout", "cli_failed"})
_DOCKER_ERRORS = frozenset({"daemon_unreachable", "timeout", "cli_failed", "parse_failed"})
_PROXMOX_ERRORS = frozenset({"timeout", "cli_failed", "parse_failed", "backup_index_incomplete"})


def _whole_number(value: object) -> int | None:
    """A VM ID, exit code or restart count from the report: an int that agent_number accepts
    (the agent sends Go ints); anything else, a fraction too, counts as missing (R-0517)."""
    number = agent_number(value)
    return number if isinstance(number, int) else None


def _outage_message(label: str, block: dict, codes: frozenset[str]) -> tuple[str, str | None]:
    """(message, code) of a block the agent could not read. The message goes unchanged into
    MonitorState.message, webhook and mail, so only a known code and a capped error_message
    get in; any other error is still an outage, just without the agent's text (R-0472)."""
    error = block.get("error")
    code = error if isinstance(error, str) and error in codes else None
    msg = f"{label} unavailable ({code})" if code else f"{label} unavailable"
    text = cap_agent_text(block.get("error_message"))
    if text:
        msg += f": {text}"
    return msg, code


class ProxmoxBackupChecker:
    """Checks whether VMs/CTs have up-to-date backups.

    Config example:
    {
        "max_backup_age_hours": 26,
        "exclude_vmids": [999],
        "exclude_stopped": true,
        "alert_on_unavailable": true
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Waiting for agent data", None

    def evaluate(
        self, config: dict, report: dict, prev_details: dict | None = None
    ) -> tuple[str, str, dict | None]:
        proxmox = report.get("proxmox")
        if not isinstance(proxmox, dict) or not proxmox:
            # An empty list, not None: the push path keeps the stored details of a
            # result without any, and the desktop would go on showing the old VMs.
            return "unknown", "No Proxmox data in report", {"_details": {"vms": []}}

        # Only a JSON false is an outage: null, 0 or "false" let the VMs decide.
        if proxmox.get("available", True) is False or proxmox.get("error"):
            msg, code = _outage_message("Proxmox", proxmox, _PROXMOX_ERRORS)
            # Only a real False switches the alert off; anything else keeps the default.
            alert = config.get("alert_on_unavailable", True) is not False
            details = {"available": False, "error": code, "vms": []}
            return ("warning" if alert else "unknown"), msg, {"_details": details}

        vms = capped_objects(proxmox.get("vms"))
        if not vms:
            return (
                "ok",
                "No VMs/CTs found",
                {"_details": {"available": True, "error": None, "vms": []}},
            )

        max_age_hours = config.get("max_backup_age_hours", 26)
        exclude_vmids = set(config.get("exclude_vmids", []))
        # Only a real False includes stopped VMs: a non-bool stored before the strict
        # boundary is the default, as the check editor shows it.
        exclude_stopped = config.get("exclude_stopped", True) is not False
        max_age_seconds = max_age_hours * 3600
        now = time.time()

        no_backup = []
        outdated = []
        ok_count = 0
        vm_details = []

        # One pass classifies each VM and builds the UI detail row, so the
        # exclude filters and age calculation live in a single place.
        for vm in vms:
            # A field of the wrong JSON type (a broken agent) counts as missing (R-0517); an
            # unreadable backup time is no backup.
            vmid = _whole_number(vm.get("vmid"))
            if vmid in exclude_vmids:
                continue
            if exclude_stopped and vm.get("status") != "running":
                continue

            # Type and name go into the message and into _details, which the desktop reads with
            # every other check in one answer: only a string, capped and on one line.
            vm_type = cap_agent_text(vm.get("type")) or "vm"
            name = cap_agent_text(vm.get("name")) or "?"
            label = f"{vm_type.upper()} {vmid} ({name})"
            last_ts = agent_number(vm.get("last_backup_ts"))
            vm_status = "ok"
            age_hours = None

            if last_ts is None:
                vm_status = "missing"
                no_backup.append(label)
            elif (now - last_ts) > max_age_seconds:
                vm_status = "outdated"
                age_hours = round((now - last_ts) / 3600)
                outdated.append(f"{label}: {age_hours}h old")
            else:
                ok_count += 1

            vm_details.append(
                {
                    "vmid": vmid,
                    "name": name,
                    "type": vm_type,
                    "backupStatus": vm_status,
                    "ageHours": age_hours,
                }
            )

        metrics = {
            "proxmox_backup_ok": ok_count,
            "proxmox_backup_missing": len(no_backup),
            "proxmox_backup_outdated": len(outdated),
            "_details": {"available": True, "error": None, "vms": vm_details},
        }

        if no_backup:
            msg = "No backup: " + join_capped(no_backup)
            if outdated:
                msg += "; Outdated: " + join_capped(outdated)
            return "critical", msg, metrics

        if outdated:
            return "warning", "Outdated backups: " + join_capped(outdated), metrics

        return "ok", f"All {ok_count} VMs/CTs have up-to-date backups", metrics


def _pool_capacity(pool: dict) -> int | float:
    """capacity_percent of a pool; anything but a JSON number counts as missing, i.e. 0
    (R-0517). The health still counts."""
    cap = agent_number(pool.get("capacity_percent"))
    return 0 if cap is None else cap


def _pool_name(pool: dict) -> str:
    """name of a pool as message and _details show it: only a string, capped and on one line
    by cap_agent_text, else "?". The metric name still reads the raw value."""
    return cap_agent_text(pool.get("name")) or "?"


class ZfsHealthChecker:
    """Checks ZFS pool health and capacity.

    Config example:
    {
        "capacity_warn": 80,
        "capacity_crit": 90,
        "alert_on_unavailable": true
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Waiting for agent data", None

    def evaluate(
        self, config: dict, report: dict, prev_details: dict | None = None
    ) -> tuple[str, str, dict | None]:
        zfs = report.get("zfs")
        if not isinstance(zfs, dict) or not zfs:
            # An empty list, not None: the push path keeps the stored details of a
            # result without any, and the desktop would go on showing the old pools.
            return "unknown", "No ZFS data in report", {"_details": {"pools": []}}

        # Only a JSON false is an outage: null, 0 or "false" let the pools decide.
        if zfs.get("available", True) is False or zfs.get("error"):
            msg, code = _outage_message("ZFS", zfs, _ZFS_ERRORS)
            # Only a real False switches the alert off; anything else keeps the default.
            alert = config.get("alert_on_unavailable", True) is not False
            details = {"available": False, "error": code, "pools": []}
            return ("warning" if alert else "unknown"), msg, {"_details": details}

        pools = capped_objects(zfs.get("pools"))
        if not pools:
            return (
                "ok",
                "No ZFS pools found",
                {"_details": {"available": True, "error": None, "pools": []}},
            )

        cap_warn = config.get("capacity_warn", 80)
        cap_crit = config.get("capacity_crit", 90)

        status = "ok"
        problems = []
        metrics = {}

        for pool in pools:
            name = pool.get("name", "?")
            shown_name = _pool_name(pool)
            health = pool.get("health", "UNKNOWN")
            cap = _pool_capacity(pool)
            metrics[f"zfs_capacity_{name}"] = cap

            if health in ("FAULTED", "OFFLINE", "UNAVAIL", "DEGRADED"):
                problems.append(f"{shown_name}: {health}")
                status = "critical"

            if cap >= cap_crit:
                problems.append(f"{shown_name}: {cap}% full (>={cap_crit}%)")
                status = "critical"
            elif cap >= cap_warn:
                problems.append(f"{shown_name}: {cap}% full (>={cap_warn}%)")
                if status != "critical":
                    status = "warning"

        metrics["_details"] = {
            "available": True,
            "error": None,
            "pools": [
                {
                    "name": _pool_name(p),
                    # The rating above reads the raw health; _details only gets a capped string.
                    "health": cap_agent_text(p.get("health")) or "UNKNOWN",
                    "capacityPercent": _pool_capacity(p),
                }
                for p in pools
            ],
        }

        if problems:
            return status, join_capped(problems, "; "), metrics

        pool_summary = join_capped([f"{_pool_name(p)} {_pool_capacity(p)}%" for p in pools])
        return "ok", f"All pools ONLINE: {pool_summary}", metrics


# docker ps prints the exit code into the status text: "Exited (3) 2 minutes ago". No exit
# code has more than 10 digits; a longer one (a broken agent) does not match and counts as
# missing, instead of failing the evaluation in int() (R-0517).
_PS_EXITED = re.compile(r"exited \((-?\d{1,10})\)", re.IGNORECASE)

# 128+SIGTERM and 128+SIGKILL: how docker stop ends an app that does not exit 0 on
# TERM, or ignores it until the stop timeout kills it. A stop, not a crash (Kevin
# 2026-10-17); an OOM kill also ends in 137 and is caught by oom_killed first.
_STOP_SIGNAL_EXITS = (137, 143)


def _ps_status(c: dict) -> str:
    """The docker ps status text; anything but a string counts as none (R-0507)."""
    status = c.get("status")
    return status if isinstance(status, str) else ""


def _container_exit_code(c: dict) -> int | None:
    exit_code = _whole_number(c.get("exit_code"))
    if exit_code is not None:
        return exit_code
    # Agents before R-0419 send no exit_code; their ps status text carries it. An exit_code
    # that is no whole JSON number counts as missing (R-0517).
    m = _PS_EXITED.match(_ps_status(c))
    return int(m.group(1)) if m else None


def _rate_container(c: dict, state: str, prev_restart_count: int | None) -> tuple[str, str | None]:
    """(category, reason code) of one container, after the table "Bewertung je
    Container" of docs/features/monitoring-silent-outages.md: the end decides, the
    restart policy only tells a deliberate stop from a crash."""
    if state == "running":
        if "health" in c:
            unhealthy = c["health"] == "unhealthy"
        else:  # agent before R-0419: only the ps status text carries it
            unhealthy = "unhealthy" in _ps_status(c).lower()
        if unhealthy:
            return "warning", "unhealthy"
        # A restart between two pushes raises the count; a manual start resets it to 0.
        count = _whole_number(c.get("restart_count"))
        if count is not None and isinstance(prev_restart_count, int) and count > prev_restart_count:
            return "warning", "restarted"
        return "ok", None
    if state in ("restarting", "dead"):
        return "critical", state
    if state == "paused":
        return "warning", "paused"
    if state == "created":
        # A failed first start leaves the container created, with the runtime's exit
        # code (127 for a missing command, Docker 29.8.1); never started is exit 0.
        if _container_exit_code(c):
            return "critical", "start_failed"
        return "stopped", "created"
    if state == "removing":
        return "stopped", "stopped"
    if state == "exited":
        if c.get("oom_killed"):
            return "critical", "oom"
        # always/unless-stopped restart a crashed container, so exited there means
        # stopped by hand (Docker ignores the policy until the next manual start).
        if c.get("restart_policy") in ("always", "unless-stopped"):
            return "stopped", "stopped"
        exit_code = _container_exit_code(c)
        if exit_code and exit_code not in _STOP_SIGNAL_EXITS:
            return "critical", f"exit:{exit_code}"
        return "stopped", "stopped"
    return "warning", "unknown_state"


def _problem_text(name: str, reason: str, state: str) -> str:
    if reason.startswith("exit:"):
        return f"{name}: exited with code {reason[5:]}"
    if reason == "oom":
        return f"{name}: OOM-killed"
    if reason == "start_failed":
        return f"{name}: failed to start"
    if reason == "unknown_state":
        return f"{name}: unknown state {state!r}"
    return f"{name}: {reason}"


class DockerHealthChecker:
    """Checks Docker container status.

    Config example:
    {
        "ignore_containers": ["watchtower"],
        "alert_on_unavailable": true
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Waiting for agent data", None

    def evaluate(
        self, config: dict, report: dict, prev_details: dict | None = None
    ) -> tuple[str, str, dict | None]:
        """`prev_details` is this check's previous `_details` blob (state.details): a
        container whose restart_count rose since then restarted between two pushes."""
        docker = report.get("docker")
        if not isinstance(docker, dict) or not docker:
            # An empty list, not None: the push path keeps the stored details of a
            # result without any, and the desktop would go on showing the old list.
            return "unknown", "No Docker data in report", {"_details": {"containers": []}}

        # Only a JSON false is an outage: null, 0 or "false" let the containers decide.
        if docker.get("available", True) is False or docker.get("error"):
            msg, code = _outage_message("Docker", docker, _DOCKER_ERRORS)
            # Only a real False switches the alert off; anything else keeps the default.
            alert = config.get("alert_on_unavailable", True) is not False
            details = {"available": False, "error": code, "containers": []}
            return ("warning" if alert else "unknown"), msg, {"_details": details}

        containers = capped_objects(docker.get("containers"))
        if not containers:
            return (
                "ok",
                "No containers found",
                {"_details": {"available": True, "error": None, "containers": []}},
            )

        ignore = set(config.get("ignore_containers", []))
        # The agent sends the 12-char short ID as a string; any other entry or ID (a list is
        # not even hashable) has no previous value instead of failing the whole evaluation.
        prev = (prev_details or {}).get("containers")
        prev_restarts = {
            p["id"]: p.get("restart_count")
            for p in (prev if isinstance(prev, list) else [])
            if isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"]
        }

        critical_problems = []
        warning_problems = []
        ok_count = 0
        running = 0
        stopped = 0
        container_details = []

        for c in containers:
            cid = c.get("id")
            # A name or state that is no string (a broken agent, R-0507) counts as missing.
            name = c.get("name")
            if not isinstance(name, str):
                name = cid if isinstance(cid, str) else "?"
            if name in ignore:
                continue

            state = c.get("state")
            state = state.lower() if isinstance(state, str) else ""
            # _details stores the ID capped like the name, and the previous details are the
            # stored ones: the lookup goes by the capped ID, so an ID the cap changes keeps its
            # previous value.
            shown_id = cap_agent_text(cid)
            prev_count = prev_restarts.get(shown_id) if shown_id else None
            category, reason = _rate_container(c, state, prev_count)
            # The ignore list and the rating read the full name and state; message and details
            # only get a capped copy, the message goes unchanged into webhook and mail (R-0508).
            shown_name = cap_agent_text(name) or ""
            shown_state = cap_agent_text(state) or ""
            if state == "running":
                running += 1
            if category == "critical":
                critical_problems.append(_problem_text(shown_name, reason, shown_state))
            elif category == "warning":
                warning_problems.append(_problem_text(shown_name, reason, shown_state))
            elif category == "stopped":
                stopped += 1
            else:
                ok_count += 1

            container_details.append(
                {
                    "id": shown_id,
                    "name": shown_name,
                    "image": cap_agent_text(c.get("image")) or "",
                    "state": shown_state,
                    "category": category,
                    "reason": reason,
                    "exit_code": _container_exit_code(c),
                    "restart_count": _whole_number(c.get("restart_count")),
                }
            )

        metrics = {
            "docker_ok": ok_count,
            "docker_critical": len(critical_problems),
            "docker_warning": len(warning_problems),
        }
        metrics["_details"] = {"available": True, "error": None, "containers": container_details}

        counts = f"{running} running, {stopped} stopped"
        if critical_problems:
            msg = "Container problems: " + join_capped(critical_problems)
            if warning_problems:
                msg += "; warnings: " + join_capped(warning_problems)
            return "critical", f"{msg} ({counts})", metrics

        if warning_problems:
            return (
                "warning",
                f"Container warnings: {join_capped(warning_problems)} ({counts})",
                metrics,
            )

        if stopped or not running:
            return "ok", counts, metrics
        return "ok", f"All {running} containers running", metrics
