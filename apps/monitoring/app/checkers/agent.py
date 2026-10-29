# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent-based checkers.

Evaluate agent push data against configurable thresholds.
The data comes from the adminhelper-agent via POST /agent/{server_id}/report.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta
from fnmatch import fnmatchcase

from app.core.time import utcnow_naive

logger = logging.getLogger("monitor.agent")

# Pseudo filesystems ignored during disk evaluation
EXCLUDED_FSTYPES = {"", "squashfs", "tmpfs", "devtmpfs", "overlay"}

# Name of a disk reported without a mount. Grading (disk:<mount>), ignore_mounts and
# _details must share it, or the desktop rates the disk under another key; the push
# handler (routers/agent.py) writes it as the mount tag, so disk_forecast keeps the disk's
# series apart (R-0753). No path, so it never collides with "/".
NO_MOUNT = "?"

# The virtualization systems the host facts report with the role guest for a container:
# the agent's containerSystems (system_linux.go, gopsutil v4.26.5, no Podman), kept equal
# by test_agent_resources_checker.py. A tuple, because `in` on it compares instead of
# hashing, so a system that is a list or an object cannot raise.
_CONTAINER_SYSTEMS = ("lxc", "docker", "openvz", "rkt")

# In-memory map: server_id -> last report time (naive UTC wall clock). Process-
# local (single-worker invariant, see main.py lifespan); hydrated at startup
# from monitor_agent_liveness so a restart no longer makes agent_ping fall back
# to 'unknown' until the next push. Wall clock instead of time.monotonic on
# purpose — a monotonic value cannot be persisted across processes.
_last_report: dict[str, datetime] = {}
# Monotonic companion to _last_report, same key. Only the wall-clock value can be
# persisted across processes, but comparing BOTH deltas reveals a clock jump:
# wall time can leap (NTP step, VM suspend/resume), monotonic time cannot. Absent
# for a server hydrated from the DB after a restart — then the wall clock alone
# decides, exactly as before.
_last_report_mono: dict[str, float] = {}

# A wall/monotonic divergence above this counts as "the clock jumped", not as
# elapsed time. Both clocks are read a few statements apart, so only measurement
# noise and a concurrent push landing between the two reads can diverge them at
# all — 60 s is far above either. Correcting is safe in both directions, so the
# constant only decides WHEN to prefer monotonic, never whether to alert.
_CLOCK_JUMP_TOLERANCE_SECONDS = 60.0

# Longest text from the report a checker copies into its message. The message goes into
# MonitorState.message (cut only at check_engine.MAX_MESSAGE, 2000 characters) and from there
# into webhook and mail, so a broken or hijacked agent must not push an unbounded text
# through it (R-0437).
MAX_AGENT_TEXT = 500

# Every control character (Unicode category Cc: C0, DEL, C1) and the line and paragraph
# separators become a space, one for one: a line break in a container name would otherwise
# start a forged line of its own in the dashboard, the bell, mail and webhook.
_AGENT_TEXT_TO_SPACE = str.maketrans(
    dict.fromkeys([*range(0x20), *range(0x7F, 0xA0), 0x2028, 0x2029], " ")
)


def cap_agent_text(value: object) -> str | None:
    """A text from the report as it may go into a message: a non-empty string on one line,
    every control character a space, cut to MAX_AGENT_TEXT characters including the trailing
    "…"; None for anything else.

    Cut first, then translate: the table maps one character to one, so the result is the
    same, and the work stays bounded by MAX_AGENT_TEXT however long the report text is."""
    if not isinstance(value, str) or not value:
        return None
    if len(value) <= MAX_AGENT_TEXT:
        return value.translate(_AGENT_TEXT_TO_SPACE)
    return value[: MAX_AGENT_TEXT - 1].translate(_AGENT_TEXT_TO_SPACE) + "…"


# A list a checker joins into its message names at most this many entries and characters
# (entries and separators); the full list is in _details (R-0517).
_MAX_LIST_ENTRIES = 10
_MAX_LIST_TEXT = 1000


def join_capped(entries: list[str], sep: str = ", ") -> str:
    """entries joined with sep as they may go into a message: each entry on one line and cut
    by cap_agent_text, appended in order as long as the joined text keeps to _MAX_LIST_ENTRIES
    entries and _MAX_LIST_TEXT characters (the first always fits), the rest counted as
    " (+N more)". Up to ten short one-line entries give sep.join(entries)."""
    named: list[str] = []
    length = 0
    for entry in entries[:_MAX_LIST_ENTRIES]:
        text = cap_agent_text(entry) or ""  # None for an empty entry
        added = len(text) + (len(sep) if named else 0)
        if length + added > _MAX_LIST_TEXT:
            break
        named.append(text)
        length += added
    joined = sep.join(named)
    rest = len(entries) - len(named)
    return f"{joined} (+{rest} more)" if rest else joined


def agent_number(value: object) -> int | float | None:
    """A number from the report as a checker may rate it: an int or float (no bool) that
    converts to a finite float, unchanged; None for anything else, a numeric string too.
    None means the field counts as missing (R-0517)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        finite = math.isfinite(value)
    except OverflowError:  # an int beyond float range, e.g. 400 digits
        return None
    return value if finite else None


# The one cap on a report list for the checkers and the push handler (routers/agent.py),
# applied in two places: capped_objects for lists of objects, ServiceProcessChecker._capped
# for the unit lists. A compromised or misconfigured agent must not flood the service with
# a huge list (3.76, R-0632).
_MAX_REPORT_ENTRIES = 500


def capped_objects(value: object) -> list[dict]:
    """The entries of a report list that a checker rates: the objects among the first
    _MAX_REPORT_ENTRIES, [] for anything but a list. Capping first bounds the work on a
    flooded list; any other entry is skipped instead of failing the evaluation (R-0486)."""
    if not isinstance(value, list):
        return []
    return [entry for entry in value[:_MAX_REPORT_ENTRIES] if isinstance(entry, dict)]


def entry_text(entry: dict, key: str, default: str) -> str:
    """A text field of a report entry; anything but a string counts as missing (R-0517)."""
    value = entry.get(key)
    return value if isinstance(value, str) else default


def entry_number(entry: dict, key: str, default: float) -> float:
    """A number field of a report entry; anything but a JSON number counts as missing."""
    value = agent_number(entry.get(key))
    return default if value is None else value


def record_agent_report(server_id: str) -> None:
    """Called on agent push to store the timestamp."""
    _last_report[server_id] = utcnow_naive()
    _last_report_mono[server_id] = time.monotonic()


def hydrate_agent_liveness(entries: dict[str, datetime]) -> None:
    """Seed _last_report from the persisted monitor_agent_liveness rows at
    startup. setdefault: a push that arrived before hydration must not be
    overwritten by an older persisted value."""
    for server_id, last_report_at in entries.items():
        _last_report.setdefault(server_id, last_report_at)
        # Deliberately NO monotonic companion: the persisted value predates this
        # process, so there is nothing to compare against. The guard stays off
        # for that server until its next push (wall-clock behavior as before).


class AgentPingChecker:
    """Checks whether the agent has reported within a time window.

    Config example:
    {
        "stale_minutes": 15
    }

    This check is run by the scheduler (not on push).
    It checks the last report timestamp from the in-memory map.
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        server_id = config.get("server_id", "")
        # Default 15 = three missed 5-minute push intervals. The old default of
        # 5 equalled the agent's push cadence and flagged a single late report
        # as critical.
        stale_minutes = config.get("stale_minutes", 15)

        if not server_id:
            return "unknown", "No server_id configured", None

        last = _last_report.get(server_id)
        if last is None:
            return "unknown", "No agent report received yet", None

        now = utcnow_naive()
        age_seconds = (now - last).total_seconds()

        # Clock-jump correction. Both stamps are taken in THIS process, so a
        # divergence means the MONITORING host's clock moved (NTP step, resumed
        # VM) — not the monitored server's. Monotonic time is then the truth:
        # re-anchor the stored wall stamp to it and grade on the real age.
        #
        # Deliberately a CORRECTION, not a bail-out: returning 'unknown' here
        # would (a) declare a genuinely dead agent fresh and fire a recovery,
        # and (b) drop agent_ping out of the host-down inhibition (which matches
        # status == 'critical'), releasing every suppressed check of that host
        # at once. Correcting keeps the verdict truthful in both directions —
        # a fresh agent stays ok, a dead one stays critical.
        last_mono = _last_report_mono.get(server_id)
        if last_mono is not None:
            mono_age = time.monotonic() - last_mono
            if abs(age_seconds - mono_age) > _CLOCK_JUMP_TOLERANCE_SECONDS:
                logger.info(
                    "Clock jump on the monitoring host (%s): wall age %.0fs vs monotonic %.0fs "
                    "— heartbeat anchor corrected by %.0fs, verdict unchanged",
                    server_id,
                    age_seconds,
                    mono_age,
                    age_seconds - mono_age,
                )
                age_seconds = mono_age
                _last_report[server_id] = now - timedelta(seconds=mono_age)
        elif age_seconds < 0:
            # No monotonic companion (hydrated from the DB after a restart) and
            # the stored stamp lies in the future: the clock moved backwards
            # before this process started. Treat it as "just seen" rather than
            # reporting a negative age.
            logger.info("Future heartbeat stamp for %s — clamped to 0s", server_id)
            age_seconds = 0.0

        age_minutes = age_seconds / 60

        if age_minutes > stale_minutes:
            return (
                "critical",
                f"Agent unreachable for {age_minutes:.0f} min (limit: {stale_minutes} min)",
                {"agent_last_seen_seconds": round(age_seconds)},
            )

        return (
            "ok",
            f"Agent active (last report {age_seconds:.0f}s ago)",
            {"agent_last_seen_seconds": round(age_seconds)},
        )


def _grade(
    value: float,
    warn: float,
    crit: float,
    label: str,
    unit: str,
    problems: list[str],
    status: str,
    warn_release: float = 0.0,
    crit_release: float = 0.0,
) -> tuple[str, str | None]:
    """Escalate `status` for one threshold measurement: >= crit -> critical, >= warn
    -> warning (never downgrading an already-critical status). Appends the breached
    `label` plus the crossed threshold to `problems`. Shared by every metric of
    agent_resources so the escalation rule lives in one place (2.31).

    Hysteresis (T6): `warn_release`/`crit_release` lower the respective threshold
    for a metric that already sat at that level last round — a value hovering at
    the edge stays in its band until it clears entry − hysteresis_pp
    (Netdata-style entry/release). Returns (status, level): level is this
    metric's own grade (None/"warning"/"critical"), remembered for next round."""
    if value >= crit - crit_release:
        problems.append(f"{label} (>={crit}{unit})")
        return "critical", "critical"
    if value >= warn - warn_release:
        problems.append(f"{label} (>={warn}{unit})")
        return ("critical" if status == "critical" else "warning"), "warning"
    return status, None


def _in_container(report: dict) -> bool:
    """Whether the host facts of this push report a container. Without them (no host
    block, or a virtualization the agent could not read) it is none."""
    host = report.get("host")
    virt = host.get("virtualization") if isinstance(host, dict) else None
    return (
        isinstance(virt, dict)
        and virt.get("role") == "guest"
        and virt.get("system") in _CONTAINER_SYSTEMS
    )


class _Grader:
    """Problems, worst status and per-metric levels of one agent_resources round.

    Hysteresis memory is per METRIC (not per check) on purpose: a shared
    flag would let an alerting CPU lower the disk thresholds and create a
    self-sustaining warning for a metric that never crossed entry."""

    def __init__(self, config: dict, prev_details: dict | None) -> None:
        self.hysteresis_pp = config.get("hysteresis_pp", 10)
        prev_problems = (prev_details or {}).get("problems") or {}
        self.prev_problems = prev_problems if isinstance(prev_problems, dict) else {}
        self.problems: list[str] = []
        self.status = "ok"
        self.problem_levels: dict[str, str] = {}

    def grade(
        self,
        key: str,
        value: float,
        warn: float,
        crit: float,
        label: str,
        unit: str,
        hysteresis: bool = True,
    ) -> None:
        prev_level = self.prev_problems.get(key) if hysteresis else None
        warn_rel = self.hysteresis_pp if prev_level in ("warning", "critical") else 0.0
        crit_rel = self.hysteresis_pp if prev_level == "critical" else 0.0
        self.status, level = _grade(
            value, warn, crit, label, unit, self.problems, self.status, warn_rel, crit_rel
        )
        if level:
            self.problem_levels[key] = level


def _grade_usage(grader: _Grader, config: dict, resources: dict) -> tuple:
    """CPU, RAM and swap: (cpu, memory, swap, swap_total_mb) as read."""
    # CPU and memory: no metric here, as with disks and temperatures below. The agent
    # router already writes monitor_agent_cpu_percent/monitor_agent_memory_percent per
    # server; a copy with this check's labels was a second series of the same name
    # (R-0633). Still graded below.
    cpu = agent_number(resources.get("cpu_percent"))
    if cpu is not None:
        cpu_crit = config.get("cpu_crit", 95)
        cpu_warn = config.get("cpu_warn", 80)
        grader.grade("cpu", cpu, cpu_warn, cpu_crit, f"CPU {cpu}%", "%")

    # Memory
    mem = agent_number(resources.get("memory_percent"))
    if mem is not None:
        mem_crit = config.get("memory_crit", 95)
        mem_warn = config.get("memory_warn", 80)
        grader.grade("memory", mem, mem_warn, mem_crit, f"RAM {mem}%", "%")

    # Swap (agent v3, Linux): a host without a swap device sends swap_total_mb 0.
    swap = agent_number(resources.get("swap_percent"))
    swap_total = agent_number(resources.get("swap_total_mb"))
    if swap is not None and swap_total is not None and swap_total > 0:
        swap_crit = config.get("swap_crit", 95)
        swap_warn = config.get("swap_warn", 80)
        grader.grade("swap", swap, swap_warn, swap_crit, f"Swap {swap}%", "%")
    return cpu, mem, swap, swap_total


def _grade_load(
    grader: _Grader, config: dict, resources: dict, load_rated: bool
) -> tuple[int | None, float | None]:
    """Load per CPU: (cpu_count, load_per_cpu) as read."""
    # Load per CPU (agent v3, Linux): older agents send load_5m without cpu_count.
    # No hysteresis: hysteresis_pp is in percentage points, and load_5m is the
    # kernel's own 5-minute average, already smoothed whatever the push interval.
    # Not rated in a container, only shown: load_5m is the host's there (unless
    # lxcfs virtualizes /proc/loadavg), while cpu_count may be cut to the
    # container's cores, so the quotient says nothing about the container.
    cpu_count = agent_number(resources.get("cpu_count"))
    if not isinstance(cpu_count, int) or cpu_count < 1:
        cpu_count = None
    load_5m = agent_number(resources.get("load_5m"))
    load_per_cpu = None
    if cpu_count is not None and load_5m is not None:
        # Rounded before grading, so the label shows the value that was graded.
        load_per_cpu = round(load_5m / cpu_count, 2)
        if load_rated:
            load_crit = config.get("load_crit", 3.0)
            load_warn = config.get("load_warn", 1.5)
            grader.grade(
                "load",
                load_per_cpu,
                load_warn,
                load_crit,
                f"Load {load_per_cpu}/CPU",
                "/CPU",
                hysteresis=False,
            )
    return cpu_count, load_per_cpu


def _grade_disks(grader: _Grader, config: dict, resources: dict) -> tuple[list[dict], set]:
    """Usage and inodes per disk: (the disks after the fstype filter, ignore_mounts)."""
    # Disks — filter pseudo filesystems server-side
    # Old agents send no fstype → default "_real_" passes the filter, as does a non-string
    raw_disks = capped_objects(resources.get("disks"))
    disks = [d for d in raw_disks if entry_text(d, "fstype", "_real_") not in EXCLUDED_FSTYPES]

    disk_crit = config.get("disk_crit", 95)
    disk_warn = config.get("disk_warn", 85)
    disk_min_free_gb = config.get("disk_min_free_gb", 20)
    ignore_mounts = set(config.get("ignore_mounts", []))
    disk_overrides = config.get("disk_overrides", {})
    inode_crit = config.get("inode_crit", 90)
    inode_warn = config.get("inode_warn", 80)
    for disk in disks:
        pct = entry_number(disk, "percent", 0)
        mount = entry_text(disk, "mount", NO_MOUNT)
        if mount in ignore_mounts:
            continue
        # The schema takes null for an override key; it counts as unset, like a missing one.
        ov = {k: v for k, v in disk_overrides.get(mount, {}).items() if v is not None}
        d_warn = ov.get("warn", disk_warn)
        d_crit = ov.get("crit", disk_crit)
        min_free_gb = ov.get("min_free_gb", disk_min_free_gb)
        # Agent v3 sends free_gb: the percentage counts only below min_free_gb free, 0
        # turns the gate off. Without free_gb (older agent) it counts as before.
        free_gb = agent_number(disk.get("free_gb"))
        if free_gb is None or min_free_gb == 0 or free_gb < min_free_gb:
            label = f"Disk {mount} {pct}%"
            if free_gb is not None:
                label += f", {free_gb} GB free"
            # No per-mount metric: the agent router already writes monitor_agent_disk_percent
            # dimensionally (mount tag). Encoding the mount into the metric NAME here was a
            # duplicate series in a second schema (1.18); the value is still graded below.
            grader.grade(f"disk:{mount}", pct, d_warn, d_crit, label, "%")
        # Agent v3 on Linux, and only for a filesystem that reports inodes.
        inodes = agent_number(disk.get("inodes_percent"))
        if inodes is not None:
            grader.grade(
                f"inode:{mount}",
                inodes,
                inode_warn,
                inode_crit,
                f"Inodes {mount} {inodes}%",
                "%",
            )
    return disks, ignore_mounts


def _grade_temperatures(grader: _Grader, config: dict, resources: dict) -> list[dict]:
    # Temperatures (optional — VMs provide no sensor data)
    temperatures = capped_objects(resources.get("temperatures"))
    if temperatures:
        temp_crit = config.get("temp_crit", 95)
        temp_warn = config.get("temp_warn", 80)
        temp_overrides = config.get("temp_overrides", {})
        for sensor in temperatures:
            temp_c = entry_number(sensor, "temp_c", 0)
            sensor_name = entry_text(sensor, "sensor", "?")
            # Same as disks: the router writes monitor_agent_temp dimensionally (sensor
            # tag); the name-encoded copy here was the duplicate (1.18). Still graded below.
            ov = temp_overrides.get(sensor_name, {})
            s_crit = ov.get("crit", temp_crit)
            s_warn = ov.get("warn", temp_warn)
            grader.grade(
                f"temp:{sensor_name}",
                temp_c,
                s_warn,
                s_crit,
                f"Temp {sensor_name} {temp_c}°C",
                "°C",
            )
    return temperatures


def _resources_message(problems: list[str], cpu, mem) -> str:
    if problems:
        return join_capped(problems, "; ")
    parts = []
    if cpu is not None:
        parts.append(f"CPU {cpu}%")
    if mem is not None:
        parts.append(f"RAM {mem}%")
    return ", ".join(parts) if parts else "OK"


def _resources_details(
    resources: dict,
    *,
    cpu,
    mem,
    swap,
    swap_total,
    cpu_count: int | None,
    load_per_cpu: float | None,
    problem_levels: dict[str, str],
    disks: list[dict],
    ignore_mounts: set,
    temperatures: list[dict],
) -> dict:
    return {
        "cpu": cpu,
        "memory": mem,
        # Next round's hysteresis memory (see _Grader.grade).
        "problems": problem_levels,
        "memory_total_mb": agent_number(resources.get("memory_total_mb")),
        "memory_used_mb": agent_number(resources.get("memory_used_mb")),
        "swap": swap,
        "swap_total_mb": swap_total,
        "swap_used_mb": agent_number(resources.get("swap_used_mb")),
        "cpu_count": cpu_count,
        "load_per_cpu": load_per_cpu,
        "disks": [
            {
                "mount": entry_text(d, "mount", NO_MOUNT),
                "percent": entry_number(d, "percent", 0),
                "total_gb": agent_number(d.get("total_gb")),
                "used_gb": agent_number(d.get("used_gb")),
                "free_gb": agent_number(d.get("free_gb")),
                "inodes_percent": agent_number(d.get("inodes_percent")),
                # Still listed, so the desktop shows the usage without a rating.
                "ignored": entry_text(d, "mount", NO_MOUNT) in ignore_mounts,
            }
            for d in disks
        ],
        "temperatures": [
            {
                "sensor": entry_text(s, "sensor", "?"),
                "temp_c": entry_number(s, "temp_c", 0),
                "high": entry_number(s, "high", 0),
                "critical": entry_number(s, "critical", 0),
            }
            for s in temperatures
        ],
    }


class AgentResourcesChecker:
    """Evaluates agent resource metrics against thresholds.

    Config example:
    {
        "cpu_warn": 80,
        "cpu_crit": 95,
        "memory_warn": 80,
        "memory_crit": 95,
        "disk_warn": 85,
        "disk_crit": 95,
        "swap_warn": 80,
        "swap_crit": 95,
        "inode_warn": 80,
        "inode_crit": 90,
        "load_warn": 1.5,
        "load_crit": 3.0,
        "disk_min_free_gb": 20,
        "ignore_mounts": ["/boot/efi"],
        "disk_overrides": {"/data": {"warn": 90, "crit": 95, "min_free_gb": 100}}
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        # Not called by the scheduler, but directly on agent push
        return "unknown", "Waiting for agent data", None

    def evaluate(
        self, config: dict, report: dict, prev_details: dict | None = None
    ) -> tuple[str, str, dict | None]:
        """Evaluates an agent report against thresholds.

        `prev_details` is this check's previous `_details` blob (state.details);
        its "problems" map {metric_key: level} drives the per-metric hysteresis."""
        resources = report.get("resources")
        # Anything but an object (a broken agent) counts as missing, as do the fields below.
        if not isinstance(resources, dict) or not resources:
            return "unknown", "No resource data", None

        grader = _Grader(config, prev_details)
        cpu, mem, swap, swap_total = _grade_usage(grader, config, resources)
        load_rated = not _in_container(report)
        cpu_count, load_per_cpu = _grade_load(grader, config, resources, load_rated)
        disks, ignore_mounts = _grade_disks(grader, config, resources)
        temperatures = _grade_temperatures(grader, config, resources)

        details = _resources_details(
            resources,
            cpu=cpu,
            mem=mem,
            swap=swap,
            swap_total=swap_total,
            cpu_count=cpu_count,
            load_per_cpu=load_per_cpu,
            problem_levels=grader.problem_levels,
            disks=disks,
            ignore_mounts=ignore_mounts,
            temperatures=temperatures,
        )
        # Only in a container, so the details of a host or VM stay as they were; the
        # desktop shows the load then without a rating.
        if not load_rated:
            details["load_rated"] = False

        message = _resources_message(grader.problems, cpu, mem)
        return grader.status, message, {"_details": details}


class ServiceProcessChecker:
    """Checks whether services are running (based on agent push).

    Two modes:
    - "auto": Automatically detects failed and enabled-but-inactive units
    - "list": Only checks explicitly named services (bare names mean <name>.service)

    Config example (auto; ignore entries are glob patterns):
    {
        "mode": "auto",
        "ignore": ["ModemManager.service", "drkonqi-coredump-processor@*"]
    }

    Config example (list):
    {
        "mode": "list",
        "services": ["nginx", "docker", "frpc"]
    }
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Waiting for agent data", None

    def evaluate(
        self, config: dict, report: dict, prev_details: dict | None = None
    ) -> tuple[str, str, dict | None]:
        """Evaluates the service data from the agent report.

        `prev_details` is this check's previous `_details` blob (state.details); only the
        list mode reads it, on a push without the inventory."""
        mode = config.get("mode", "list")

        if mode == "auto":
            return self._evaluate_auto(config, report)
        return self._evaluate_list(config, report, prev_details)

    @staticmethod
    def _parse_ignore(raw) -> set:
        """Normalizes the ignore list: accepts an array or a CSV string."""
        if isinstance(raw, str):
            return {s.strip() for s in raw.split(",") if s.strip()}
        if isinstance(raw, list):
            result = set()
            for item in raw:
                if isinstance(item, str) and "," in item:
                    result.update(s.strip() for s in item.split(",") if s.strip())
                elif isinstance(item, str) and item.strip():
                    result.add(item.strip())
            return result
        return set()

    # Unit type suffixes (systemd.unit(5)). A name with one of them is never read as
    # <name>.service, or "*.service" would also hide a failed data.mount.
    _UNIT_TYPES = (
        ".service",
        ".socket",
        ".device",
        ".mount",
        ".automount",
        ".swap",
        ".target",
        ".path",
        ".timer",
        ".slice",
        ".scope",
    )

    @staticmethod
    def _is_ignored(unit: str, ignore: set) -> bool:
        """Checks whether a unit matches an ignore glob (with/without .service suffix)."""
        # "nginx" should also match "nginx.service" and vice versa
        if unit.endswith(".service"):
            names = (unit, unit[:-8])
        elif unit.endswith(ServiceProcessChecker._UNIT_TYPES):
            names = (unit,)
        else:
            names = (unit, f"{unit}.service")
        return any(fnmatchcase(n, p) for n in names for p in ignore)

    @staticmethod
    def _is_service(unit: str) -> bool:
        """A .service unit, or a name without a unit suffix (a Windows service)."""
        return unit.endswith(".service") or not unit.endswith(ServiceProcessChecker._UNIT_TYPES)

    @staticmethod
    def _unit_name(name: str) -> str:
        """The unit a name stands for: a bare "nginx" is "nginx.service". Applied to both sides
        of a lookup, so a Windows service (no suffix) still finds itself."""
        if name.endswith(ServiceProcessChecker._UNIT_TYPES):
            return name
        return f"{name}.service"

    @staticmethod
    def _capped(raw) -> list:
        """Caps a unit list from the report so a huge/hostile array can't drive a DoS through
        the glob matching (3.76); a non-list value is treated as empty."""
        return raw[:_MAX_REPORT_ENTRIES] if isinstance(raw, list) else []

    @staticmethod
    def _parse_counts(raw) -> tuple[int, int] | None:
        """The agent's (active, total) service counts, or None unless both are integers that
        agent_number takes, with 0 <= active <= total. Old agents send none; a failed
        list-units/sc query leaves them out."""
        if not isinstance(raw, dict):
            return None
        # agent_number drops a bool (JSON true is no count) and an int beyond float range.
        active, total = agent_number(raw.get("active")), agent_number(raw.get("total"))
        if not all(isinstance(n, int) for n in (active, total)):
            return None
        return (active, total) if 0 <= active <= total else None

    @staticmethod
    def _not_queryable(error) -> str:
        """Message part for a failed list-units/sc query. The raw error already decided that
        listing failed; the agent's reason goes in only as a capped string."""
        reason = cap_agent_text(error)
        return f"Services not queryable: {reason}" if reason else "Services not queryable"

    def _evaluate_auto(self, config: dict, report: dict) -> tuple[str, str, dict | None]:
        """Auto mode: checks systemd health from the report.

        failed and enabled_inactive are always sent. enabled_inactive is taken as the agent
        sends it: only the agent re-checks its candidates (oneshot units that finished,
        Condition skips, Timer/Socket activation) with properties the inventory lacks, so
        the server must not re-derive the list from all_services.

        all_services, the large, mostly-static inventory, is throttled: v2 agents OMIT the
        key on most pushes. It only adds failed services systemd.failed lacks, after
        systemd.failed, so a full and a throttled push of the same state give the same
        result. The inventory is not persisted server-side, so nothing is lost by a
        throttled push.
        """
        systemd = report.get("systemd")
        if not isinstance(systemd, dict) or not systemd:
            return "unknown", "No service data in report", None

        ignore = self._parse_ignore(config.get("ignore", []))

        # Only a string is a unit name. Any other entry is skipped after the cap, so it still
        # counts toward it and the work on a flooded list stays bounded (R-0552).
        failed_raw = [u for u in self._capped(systemd.get("failed")) if isinstance(u, str)]
        for s in capped_objects(systemd.get("all_services")):
            unit = s.get("unit")
            if (
                isinstance(unit, str)
                and s.get("active_state") == "failed"
                and unit not in failed_raw
            ):
                failed_raw.append(unit)
        enabled_inactive_raw = [
            u for u in self._capped(systemd.get("enabled_inactive")) if isinstance(u, str)
        ]

        failed = [u for u in failed_raw if not self._is_ignored(u, ignore)]
        enabled_inactive = [u for u in enabled_inactive_raw if not self._is_ignored(u, ignore)]

        metrics = {
            "services_failed": len(failed),
            "services_enabled_inactive": len(enabled_inactive),
        }

        # Every name on one line and cut, as in the message; the ignore list above compared the
        # full name. An empty name stays "" (cap_agent_text gives None for it).
        metrics["_details"] = {
            "mode": "auto",
            "failed": [cap_agent_text(u) or "" for u in failed],
            "enabled_inactive": [cap_agent_text(u) or "" for u in enabled_inactive],
        }
        counts = self._parse_counts(systemd.get("counts"))
        if counts is not None:
            metrics["_details"]["active_count"], metrics["_details"]["total"] = counts

        # Only a failed service is critical; a failed mount, timer, socket or other unit is
        # warning, like an enabled but inactive unit (Kevin 2026-10-19).
        failed_services = [u for u in failed if self._is_service(u)]
        failed_units = [u for u in failed if not self._is_service(u)]
        parts = []
        if failed_services:
            parts.append(f"Failed: {join_capped(failed_services)}")
        if failed_units:
            parts.append(f"Failed units: {join_capped(failed_units)}")
        if enabled_inactive:
            parts.append(f"Inactive (autostart): {join_capped(enabled_inactive)}")

        if failed_services:
            return "critical", "; ".join(parts), metrics

        if parts:
            return "warning", "; ".join(parts), metrics

        # The agent could not list the services (systemctl list-units / sc query failed): its
        # empty lists prove nothing. On Linux failed comes from a call of its own (list-units
        # --state=failed), so a failed unit still rates the check above.
        error = systemd.get("error")
        if error:
            return "unknown", self._not_queryable(error), metrics

        return "ok", "All services OK", metrics

    @staticmethod
    def _inventory_state(entry: dict, inventory: dict, error) -> str | None:
        """running or down from an all_services entry, None if the entry says nothing."""
        if entry.get("enabled_state") == "alias":
            # list-units knows a unit by its own name only: an alias has the state of its
            # target, and without alias_of (the agent could not resolve it) none at all.
            target = entry.get("alias_of")
            if not isinstance(target, str):
                return None
            entry = inventory.get(ServiceProcessChecker._unit_name(target))
            if entry is None:
                return None
        active = entry.get("active_state")
        if active == "active":
            return "running"
        # unknown: a unit file list-units does not list. Normally that unit is not loaded, so not
        # running; after a failed list-units every state is unknown and proves nothing.
        if active == "unknown" and error:
            return None
        return "down"

    def _evaluate_list(
        self, config: dict, report: dict, prev_details: dict | None
    ) -> tuple[str, str, dict | None]:
        """List mode: checks explicitly named services, evaluated here, not by the agent.

        Provisioned agents have no watch list of their own (monitor init --services), so per
        name the first source that knows it decides: the agent's watch list
        (report["services"]), then the inventory of this push (systemd.all_services, an alias
        through its alias_of), and on a push without the inventory the state of the last
        evaluation (prev_details): the agent leaves the inventory out only while its hash,
        which covers every state, is unchanged. A full inventory is the current truth, so its
        gaps are not filled from prev_details. A name no source knows is nodata (a typo, no
        such unit, added since the last full inventory) and not down (Kevin 2026-10-16); only
        without data for any name is the check unknown.
        """
        expected = config.get("services", [])
        if not expected:
            return "ok", "No services configured", None

        systemd = report.get("systemd")
        if not isinstance(systemd, dict):
            systemd = {}
        error = systemd.get("error")

        # Lowest precedence first, so each later source overwrites what it knows.
        states: dict[str, str] = {}
        if "all_services" in systemd:
            inventory = {
                self._unit_name(s["unit"]): s
                for s in self._capped(systemd["all_services"])
                if isinstance(s, dict) and isinstance(s.get("unit"), str)
            }
            for unit, entry in inventory.items():
                state = self._inventory_state(entry, inventory, error)
                if state:
                    states[unit] = state
        else:
            for w in self._capped((prev_details or {}).get("watched")):
                # Old details (running alone, no state) were written while a missing watch
                # list meant down for every name; carrying them over would keep that false alarm.
                if (
                    isinstance(w, dict)
                    and isinstance(w.get("name"), str)
                    and w.get("state") in ("running", "down")
                ):
                    states[self._unit_name(w["name"])] = w["state"]
        for s in self._capped(report.get("services")):
            if isinstance(s, dict) and isinstance(s.get("name"), str):
                states[self._unit_name(s["name"])] = "running" if s.get("running") else "down"

        watched = []
        for name in expected:
            state = states.get(self._unit_name(name), "nodata")
            # running beside state: desktops before state read running alone (Kevin 2026-10-16).
            watched.append({"name": name, "state": state, "running": state == "running"})
        down = [w["name"] for w in watched if w["state"] == "down"]
        up = [w["name"] for w in watched if w["state"] == "running"]
        nodata = [w["name"] for w in watched if w["state"] == "nodata"]

        metrics = {"services_down": len(down), "services_up": len(up)}
        metrics["_details"] = {"mode": "list", "watched": watched}
        no_data = f"; no data: {join_capped(nodata)}" if nodata else ""

        if down:
            return (
                "critical",
                f"Services not active: {join_capped(down)}{no_data}",
                metrics,
            )

        if not up:
            message = f"Services without data: {join_capped(nodata)}"
            if error:
                message += f"; {self._not_queryable(error)}"
            return "unknown", message, metrics

        if nodata:
            return "ok", f"{len(up)} services active{no_data}", metrics

        return (
            "ok",
            f"All {len(up)} services active",
            metrics,
        )
