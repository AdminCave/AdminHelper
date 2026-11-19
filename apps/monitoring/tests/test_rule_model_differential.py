# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Differential test of the rule model (R-1558, ADR 0004): the SMART cascade, the ZFS pool
states and the Docker container rating, written as rule sets of the prototype, against today's
checkers.

Per family a sensor turns one report entry into values that hold no limit: type checks, the
kind of a disk, decoded bit fields, the exit code from the ps text, the previous restart count.
That part stays code. The rule set carries every limit and level. A number the checker reads
with a default when it is missing (0, the NVMe spare 100) is absent here, and the rule says
`if_absent: ok`; both rate it ok.

Each scenario rates one object with both and compares the level with the one the docs fix
(docs/admin/monitoring.html, docs/developer/monitoring.html,
docs/features/monitoring-silent-outages.md), or, where the docs name no case, the checker's own
test. A report of all scenarios up to a level compares each object and the check's status, the
worst of them. What the rule form rates otherwise is a deviation of its own, with the reason, for
ADR 0004.

Not covered: a report without the block and a block the agent could not read rate the check,
not an object, and stay with the check; so do the ignore lists of the config.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from app.checkers import plugins
from app.checkers.agent import agent_number, entry_text
from app.checkers.plugins import (
    DockerHealthChecker,
    ZfsHealthChecker,
    _container_exit_code,
    _ps_status,
    _whole_number,
    _zfs_details,
)
from app.checkers.smart import SmartHealthChecker

from .rule_model_prototype import RANK, Condition, Reading, Rule, Status, rate, rule_problems

NOW = 1_790_000_000
DAY = 86400


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """The ZFS checker reads the clock itself; the rules rate against the reading's time."""
    monkeypatch.setattr(plugins, "time", SimpleNamespace(time=lambda: NOW))


def _r(name: str, op: str, value: object, level, **kw) -> Rule:
    # Every value the checker reads with a default on the good side counts as fine when absent.
    return Rule(field=name, op=op, value=value, level=level, if_absent="ok", **kw)


# --- SMART ----------------------------------------------------------------------------------

# smartctl's exit status is a bit field (smartctl(8), EXIT STATUS); bits 4 to 7 rate the disk.
SMARTCTL_BITS = {
    0x10: "prefail_below_threshold",
    0x20: "threshold_in_past",
    0x40: "error_log",
    0x80: "selftest_failed",
}
SMART_NUMBERS = (
    "temp_c",
    "reported_uncorrect",
    "uncorrectable",
    "spin_retry_count",
    "reallocated_sectors",
    "reallocation_events",
    "pending_sectors",
    "udma_crc_errors",
    "critical_warning",
    "media_errors",
    "available_spare_pct",
    "percentage_used",
)


def smart_values(disk: dict) -> dict:
    """What smart._grade_disk reads of a disk, without a limit. protocol selects the checks by
    its raw value; one that is no string selects neither, as in the checker."""
    protocol = disk.get("protocol", "ATA")
    status = int(agent_number(disk.get("smartctl_status")) or 0)
    passed = disk.get("smart_passed")
    return {
        "protocol": protocol if isinstance(protocol, str) else "",
        "kind": entry_text(disk, "kind", "") or ("NVMe" if protocol == "NVMe" else "HDD"),
        # The documented truthiness: false, 0, "", [] and {} are FAILED; missing and null are
        # no verdict (R-0518), absent here.
        "smart_passed": None if passed is None else bool(passed),
        **{name: bool(status & bit) for bit, name in SMARTCTL_BITS.items()},
        **{key: agent_number(disk.get(key)) for key in SMART_NUMBERS},
    }


ATA = Condition(field="protocol", op="eq", value="ATA")
NVME = Condition(field="protocol", op="eq", value="NVMe")
# The agent sends only these kinds (determineKind in apps/agent/internal/monitor/smart.go). The
# checker gives any other kind the HDD limits; here it would get none, and saying "every kind
# but these" takes a `not in` (see the Docker deviations).
TEMP_LIMITS = {"HDD": (55, 60), "SATA-SSD": (60, 70), "NVMe": (65, 75)}

SMART_RULES = [
    # No if_absent: a disk without a verdict is not readable, unknown unless a rule holds worse.
    Rule(field="smart_passed", op="eq", value=False, level="critical"),
    _r("reported_uncorrect", "gt", 0, "critical"),
    _r("uncorrectable", "gt", 0, "critical"),
    _r("prefail_below_threshold", "eq", True, "critical"),
    _r("threshold_in_past", "eq", True, "warning"),
    _r("error_log", "eq", True, "warning"),
    _r("selftest_failed", "eq", True, "warning"),
    *(
        _r("temp_c", "ge", limit, level, key=f"temp_c.{level}.{kind}", when=on_kind)
        for kind, limits in TEMP_LIMITS.items()
        for level, limit, on_kind in zip(
            ("warning", "critical"), limits, [Condition("kind", "eq", kind)] * 2, strict=True
        )
    ),
    _r("spin_retry_count", "gt", 0, "critical", when=ATA),
    _r("reallocated_sectors", "ge", 10, "critical", when=ATA),
    _r("reallocated_sectors", "ge", 1, "warning", when=ATA),
    _r("reallocation_events", "ge", 10, "critical", when=ATA),
    _r("reallocation_events", "ge", 1, "warning", when=ATA),
    _r("pending_sectors", "ge", 5, "critical", when=ATA),
    _r("pending_sectors", "ge", 1, "warning", when=ATA),
    _r("udma_crc_errors", "gt", 0, "warning", when=ATA),
    _r("critical_warning", "ne", 0, "critical", when=NVME),
    _r("media_errors", "gt", 0, "critical", when=NVME),
    _r("available_spare_pct", "lt", 10, "critical", when=NVME),
    _r("available_spare_pct", "lt", 20, "warning", when=NVME),
    _r("percentage_used", "ge", 100, "critical", when=NVME),
    _r("percentage_used", "ge", 90, "warning", when=NVME),
]


def smart_checker(disks: list[dict], prevs: list[int | None]) -> tuple[str, list[str] | None]:
    status, _msg, metrics = SmartHealthChecker().evaluate({}, {"smart": disks})
    return status, [d["category"] for d in metrics["_details"]["disks"]]


def smart_place(i: int, entry: dict) -> dict:
    return {"device": f"/dev/disk{i}", "model": "X", **entry}


HDD = {"protocol": "ATA", "kind": "HDD", "temp_c": 30, "smart_passed": True}
SSD = {"protocol": "ATA", "kind": "SATA-SSD", "temp_c": 30, "smart_passed": True}
NVM = {
    "protocol": "NVMe", "kind": "NVMe", "temp_c": 40, "available_spare_pct": 100,
    "smart_passed": True,
}  # fmt: skip


@dataclass(frozen=True)
class Scenario:
    id: str
    entry: dict
    level: Status
    # Docker: the restart count of the same container in the push before.
    prev: int | None = None


SMART_SCENARIOS = [
    # docs/developer/monitoring.html (smart.py): smart_passed and the defaults.
    Scenario("hdd-clean", HDD, "ok"),
    Scenario("passed-false", {**HDD, "smart_passed": False}, "critical"),
    Scenario("passed-null", {**HDD, "smart_passed": None}, "unknown"),
    Scenario("passed-missing", {"protocol": "ATA", "kind": "HDD", "temp_c": 30}, "unknown"),
    Scenario(
        "passed-missing-and-reallocated",
        {"protocol": "ATA", "kind": "HDD", "reallocated_sectors": 1},
        "warning",
    ),
    Scenario("passed-zero", {**HDD, "smart_passed": 0}, "critical"),
    Scenario("passed-true", {**HDD, "smart_passed": True}, "ok"),
    Scenario("counter-as-string", {**HDD, "reallocated_sectors": "16"}, "ok"),
    Scenario("no-protocol-is-ata", {"kind": "HDD", "reallocated_sectors": 1}, "warning"),
    Scenario("no-kind-is-hdd", {"protocol": "ATA", "temp_c": 56}, "warning"),
    Scenario("nvme-no-kind-is-nvme", {**NVM, "kind": 7, "temp_c": 70}, "warning"),
    Scenario("other-protocol-common-only", {**HDD, "protocol": "SCSI", "pending_sectors": 9}, "ok"),
    # docs/admin/monitoring.html, the defaults of smart_health.
    Scenario("hdd-temp-54", {**HDD, "temp_c": 54}, "ok"),
    Scenario("hdd-temp-55", {**HDD, "temp_c": 55}, "warning"),
    Scenario("hdd-temp-60", {**HDD, "temp_c": 60}, "critical"),
    Scenario("ssd-temp-59", {**SSD, "temp_c": 59}, "ok"),
    Scenario("ssd-temp-60", {**SSD, "temp_c": 60}, "warning"),
    Scenario("ssd-temp-70", {**SSD, "temp_c": 70}, "critical"),
    Scenario("nvme-temp-64", {**NVM, "temp_c": 64}, "ok"),
    Scenario("nvme-temp-65", {**NVM, "temp_c": 65}, "warning"),
    Scenario("nvme-temp-75", {**NVM, "temp_c": 75}, "critical"),
    Scenario("reallocated-1", {**HDD, "reallocated_sectors": 1}, "warning"),
    Scenario("reallocated-9", {**HDD, "reallocated_sectors": 9}, "warning"),
    Scenario("reallocated-10", {**HDD, "reallocated_sectors": 10}, "critical"),
    Scenario("pending-1", {**HDD, "pending_sectors": 1}, "warning"),
    Scenario("pending-4", {**HDD, "pending_sectors": 4}, "warning"),
    Scenario("pending-5", {**HDD, "pending_sectors": 5}, "critical"),
    Scenario("nvme-clean", NVM, "ok"),
    Scenario("nvme-spare-20", {**NVM, "available_spare_pct": 20}, "ok"),
    Scenario("nvme-spare-19", {**NVM, "available_spare_pct": 19}, "warning"),
    Scenario("nvme-spare-10", {**NVM, "available_spare_pct": 10}, "warning"),
    Scenario("nvme-spare-9", {**NVM, "available_spare_pct": 9}, "critical"),
    Scenario("nvme-spare-missing", {"protocol": "NVMe", "kind": "NVMe", "smart_passed": 1}, "ok"),
    Scenario("nvme-used-89", {**NVM, "percentage_used": 89}, "ok"),
    Scenario("nvme-used-90", {**NVM, "percentage_used": 90}, "warning"),
    Scenario("nvme-used-100", {**NVM, "percentage_used": 100}, "critical"),
    Scenario("nvme-ignores-ata-counters", {**NVM, "reallocated_sectors": 20}, "ok"),
    Scenario("ata-ignores-nvme-counters", {**HDD, "media_errors": 5}, "ok"),
    # tests/test_smart_checker.py: what the docs do not spell out.
    Scenario("uncorrectable", {**HDD, "uncorrectable": 3}, "critical"),
    Scenario("reported-uncorrect", {**HDD, "reported_uncorrect": 1}, "critical"),
    Scenario("status-0x10", {**HDD, "smartctl_status": 0x10}, "critical"),
    Scenario("status-0x20", {**HDD, "smartctl_status": 0x20}, "warning"),
    Scenario("status-0x40", {**HDD, "smartctl_status": 0x40}, "warning"),
    Scenario("status-0x80", {**HDD, "smartctl_status": 0x80}, "warning"),
    Scenario("status-0x04-not-rated", {**HDD, "smartctl_status": 0x04}, "ok"),
    Scenario(
        "status-0x10-and-reallocated",
        {**HDD, "smartctl_status": 0x10, "reallocated_sectors": 1},
        "critical",
    ),
    Scenario("ssd-warm-and-spin-retry", {**SSD, "temp_c": 62, "spin_retry_count": 1}, "critical"),
    Scenario("spin-retry", {**HDD, "spin_retry_count": 1}, "critical"),
    Scenario("reallocation-events-1", {**HDD, "reallocation_events": 1}, "warning"),
    Scenario("reallocation-events-10", {**HDD, "reallocation_events": 10}, "critical"),
    Scenario("udma-crc", {**HDD, "udma_crc_errors": 2}, "warning"),
    Scenario("nvme-critical-warning-0x01", {**NVM, "critical_warning": 0x01}, "critical"),
    Scenario("nvme-critical-warning-0x20", {**NVM, "critical_warning": 0x20}, "critical"),
    Scenario("nvme-media-errors", {**NVM, "media_errors": 2}, "critical"),
]


# --- ZFS ------------------------------------------------------------------------------------


def zfs_values(pool: dict) -> dict:
    """What ZfsHealthChecker.evaluate reads of a pool, without a limit; the scrub and the vdev
    counters as _zfs_details gives them, so a field the desktop leaves out is not rated."""
    details = _zfs_details(pool)
    scrub = details.get("scrub", {})
    return {
        "health": pool.get("health"),
        "capacity_percent": agent_number(pool.get("capacity_percent")),
        "scrub_state": scrub.get("state"),
        "scrub_end": scrub.get("end"),
        "vdevs_with_errors": sum(
            1 for v in details.get("vdevErrors", []) if any(v[k] for k in plugins._VDEV_COUNTERS)
        ),
    }


FINISHED = Condition(field="scrub_state", op="eq", value="FINISHED")

ZFS_RULES = [
    _r("health", "in", ["FAULTED", "OFFLINE", "UNAVAIL", "DEGRADED"], "critical"),
    _r("capacity_percent", "ge", 90, "critical"),
    _r("capacity_percent", "ge", 80, "warning"),
    _r("scrub_end", "max_age", 60 * DAY, "critical", when=FINISHED),
    _r("scrub_end", "max_age", 35 * DAY, "warning", when=FINISHED),
    _r("vdevs_with_errors", "gt", 0, "warning"),
]


def zfs_checker(pools: list[dict], prevs: list[int | None]) -> tuple[str, list[str] | None]:
    # The details carry no category per pool: only the check's status compares.
    return ZfsHealthChecker().evaluate({}, {"zfs": {"pools": pools}})[0], None


def zfs_place(i: int, entry: dict) -> dict:
    return {"name": f"tank{i}", **entry}


POOL = {"health": "ONLINE", "capacity_percent": 40}


def _scrub(state: str, age_days: float | None) -> dict:
    scrub: dict = {"state": state, "errors": 0}
    if age_days is not None:
        scrub["end"] = int(NOW - age_days * DAY)
    return {**POOL, "scrub": scrub}


def _vdev(**counts) -> dict:
    return {
        **POOL,
        "vdev_errors": [{"name": "sda", "read": 0, "write": 0, "checksum": 0, **counts}],
    }


# docs/developer/monitoring.html (Pools von zfs_health) and docs/admin/monitoring.html; the
# scrub ends lie an hour or more away from the day limits (see the deviation for the limit).
ZFS_SCENARIOS = [
    Scenario("online", POOL, "ok"),
    *(
        Scenario(h.lower(), {**POOL, "health": h}, "critical")
        for h in ("DEGRADED", "FAULTED", "OFFLINE", "UNAVAIL")
    ),
    Scenario("health-missing", {"capacity_percent": 40}, "ok"),
    Scenario("capacity-79", {**POOL, "capacity_percent": 79}, "ok"),
    Scenario("capacity-80", {**POOL, "capacity_percent": 80}, "warning"),
    Scenario("capacity-89", {**POOL, "capacity_percent": 89}, "warning"),
    Scenario("capacity-90", {**POOL, "capacity_percent": 90}, "critical"),
    Scenario("capacity-missing", {"health": "ONLINE"}, "ok"),
    Scenario("scrub-10-days", _scrub("FINISHED", 10), "ok"),
    Scenario("scrub-35-days-less-an-hour", _scrub("FINISHED", 35 - 1 / 24), "ok"),
    Scenario("scrub-36-days", _scrub("FINISHED", 36), "warning"),
    Scenario("scrub-61-days", _scrub("FINISHED", 61), "critical"),
    Scenario("scrub-finished-without-end", _scrub("FINISHED", None), "ok"),
    Scenario("scrub-scanning-old", _scrub("SCANNING", 90), "ok"),
    Scenario("scrub-canceled-old", _scrub("CANCELED", 90), "ok"),
    Scenario("vdev-clean", _vdev(), "ok"),
    Scenario("vdev-checksum", _vdev(checksum=2), "warning"),
    Scenario("degraded-and-vdev", {**_vdev(read=1), "health": "DEGRADED"}, "critical"),
    Scenario("full-and-old-scrub", {**_scrub("FINISHED", 61), "capacity_percent": 85}, "critical"),
]


# --- Docker ---------------------------------------------------------------------------------


def docker_values(c: dict) -> dict:
    """What plugins._rate_container reads of a container, without a rating."""
    state = c.get("state")
    if "health" in c:
        health = c["health"]
    else:  # agents before R-0419: only the ps status text carries it
        health = "unhealthy" if "unhealthy" in _ps_status(c).lower() else None
    return {
        "state": state.lower() if isinstance(state, str) else "",
        "health": health,
        "restart_count": _whole_number(c.get("restart_count")),
        "exit_code": _container_exit_code(c),
        "oom_killed": bool(c.get("oom_killed")),
        "restart_policy": c.get("restart_policy"),
    }


RUNNING = Condition(field="state", op="eq", value="running")
CREATED = Condition(field="state", op="eq", value="created")
EXITED = Condition(field="state", op="eq", value="exited")

DOCKER_RULES = [
    _r("state", "in", ["restarting", "dead"], "critical"),
    _r("state", "eq", "paused", "warning"),
    _r("health", "eq", "unhealthy", "warning", when=RUNNING),
    _r("restart_count", "rises", None, "warning", when=RUNNING),
    _r("exit_code", "ne", 0, "critical", key="start_failed", when=CREATED),
    _r("oom_killed", "eq", True, "critical", when=EXITED),
    _r(
        "exit_code",
        "ne",
        0,
        "critical",
        key="crashed",
        when=EXITED,
        unless={"field": "restart_policy", "value": "always"},
    ),
]


def docker_checker(containers: list[dict], prevs: list[int | None]) -> tuple[str, list[str] | None]:
    prev_details = {
        "containers": [
            {"id": c["id"], "restart_count": p}
            for c, p in zip(containers, prevs, strict=True)
            if p is not None
        ]
    }
    status, _msg, metrics = DockerHealthChecker().evaluate(
        {}, {"docker": {"containers": containers}}, prev_details
    )
    # A stopped container counts as ok for the check's status.
    return status, [
        "ok" if d["category"] == "stopped" else d["category"]
        for d in metrics["_details"]["containers"]
    ]


def docker_place(i: int, entry: dict) -> dict:
    return {"id": f"{i:012x}", "name": f"app-{i:02d}", "image": "app:1", **entry}


UP = {"state": "running", "restart_policy": "no", "restart_count": 0}


def _exited(code: int | None, policy: str = "no", **kw) -> dict:
    return {"state": "exited", "restart_policy": policy, "exit_code": code, **kw}


# docs/admin/monitoring.html (Docker-Check) and the table "Bewertung je Container" of
# docs/features/monitoring-silent-outages.md.
DOCKER_SCENARIOS = [
    Scenario("running", UP, "ok"),
    Scenario("running-unhealthy", {**UP, "health": "unhealthy"}, "warning"),
    Scenario("running-starting", {**UP, "health": "starting"}, "ok"),
    Scenario("running-healthy", {**UP, "health": "healthy"}, "ok"),
    Scenario("running-unhealthy-ps-text", {**UP, "status": "Up 2 hours (unhealthy)"}, "warning"),
    Scenario("running-restarted", {**UP, "restart_count": 3}, "warning", prev=2),
    Scenario("running-same-count", {**UP, "restart_count": 3}, "ok", prev=3),
    Scenario("running-count-reset", {**UP, "restart_count": 0}, "ok", prev=5),
    Scenario("running-first-push", {**UP, "restart_count": 3}, "ok"),
    Scenario("restarting", {"state": "restarting"}, "critical"),
    Scenario("dead", {"state": "dead"}, "critical"),
    Scenario("paused", {"state": "paused"}, "warning"),
    Scenario("paused-unhealthy", {"state": "paused", "health": "unhealthy"}, "warning"),
    Scenario("created-never-started", {"state": "created", "exit_code": 0}, "ok"),
    Scenario("created-start-failed", {"state": "created", "exit_code": 127}, "critical"),
    Scenario("exited-oom", _exited(137, oom_killed=True), "critical"),
    Scenario("exited-oom-policy-always", _exited(137, "always", oom_killed=True), "critical"),
    Scenario("exited-policy-always", _exited(1, "always"), "ok"),
    Scenario("exited-on-failure", _exited(3, "on-failure"), "critical"),
    Scenario("exited-policy-no", _exited(3), "critical"),
    Scenario("exited-policy-empty", _exited(3, ""), "critical"),
    Scenario("exited-segfault", _exited(139), "critical"),
    Scenario("exited-0", _exited(0), "ok"),
    Scenario("exited-no-code", _exited(None), "ok"),
    Scenario(
        "exited-ps-text", {"state": "exited", "status": "Exited (3) 2 minutes ago"}, "critical"
    ),
    Scenario("removing", {"state": "removing"}, "ok"),
    Scenario("state-upper-case", {**UP, "state": "Paused"}, "warning"),
]


# --- the comparison -------------------------------------------------------------------------


@dataclass(frozen=True)
class Family:
    check: str
    sensor: Callable[[dict], dict]
    rules: list[Rule]
    scenarios: list[Scenario]
    # (check status, level per object or None) of entries placed in one report.
    checker: Callable[[list[dict], list[int | None]], tuple[str, list[str] | None]]
    place: Callable[[int, dict], dict]
    deviations: list[Deviation] = field(default_factory=list)


@dataclass(frozen=True)
class Deviation:
    """A case the rule form rates otherwise than the checker: both levels and why, for
    ADR 0004."""

    id: str
    entry: dict
    checker: Status
    rules: Status
    reason: str


def rules_level(family: Family, entry: dict, prev: int | None = None) -> Status:
    before = None if prev is None else {"restart_count": prev}
    return rate(family.rules, Reading(family.sensor(entry), NOW, before), check=family.check)[0]


def checker_level(family: Family, entry: dict, prev: int | None = None) -> str:
    return family.checker([family.place(0, entry)], [prev])[0]


SMART = Family(
    "smart_health", smart_values, SMART_RULES, SMART_SCENARIOS, smart_checker, smart_place
)
ZFS = Family(
    "zfs_health",
    zfs_values,
    ZFS_RULES,
    ZFS_SCENARIOS,
    zfs_checker,
    zfs_place,
    [
        Deviation(
            "scrub-exactly-35-days",
            _scrub("FINISHED", 35),
            checker="warning",
            rules="ok",
            reason="max_age is strict and counts seconds (probe), the checker counts whole days "
            "from 35 on: the rule warns one second later",
        ),
    ],
)
DOCKER = Family(
    "docker_health",
    docker_values,
    DOCKER_RULES,
    DOCKER_SCENARIOS,
    docker_checker,
    docker_place,
    [
        Deviation(
            "exited-143-policy-no",
            _exited(143),
            checker="ok",
            rules="critical",
            reason="exit 143 and 137 without OOM are docker stop, not a crash (Kevin 2026-10-17); "
            "leaving two codes out of exit_code ne 0 takes a `not in` or a second unless",
        ),
        Deviation(
            "exited-1-unless-stopped",
            _exited(1, "unless-stopped"),
            checker="ok",
            rules="critical",
            reason="always and unless-stopped both mean stopped by hand; `unless` takes one value",
        ),
        Deviation(
            "unknown-state",
            {"state": "migrating"},
            checker="warning",
            rules="ok",
            reason="any state but the known ones is a warning: a `not in` over the state list",
        ),
    ],
)
FAMILIES = [SMART, ZFS, DOCKER]
SINGLE = [pytest.param(f, s, id=f"{f.check}:{s.id}") for f in FAMILIES for s in f.scenarios]
DEVIATIONS = [pytest.param(f, d, id=f"{f.check}:{d.id}") for f in FAMILIES for d in f.deviations]


@pytest.mark.parametrize("family", FAMILIES, ids=lambda f: f.check)
def test_each_rule_set_holds_together(family):
    assert rule_problems(family.rules, (family.check,)) == []


@pytest.mark.parametrize(("family", "scenario"), SINGLE)
def test_the_rules_rate_each_object_as_the_checker(family, scenario):
    assert checker_level(family, scenario.entry, scenario.prev) == scenario.level
    assert rules_level(family, scenario.entry, scenario.prev) == scenario.level


@pytest.mark.parametrize("worst", ["ok", "warning", "critical"])
@pytest.mark.parametrize("family", FAMILIES, ids=lambda f: f.check)
def test_the_check_is_its_worst_object_in_both(family, worst):
    picked = [s for s in family.scenarios if RANK[s.level] <= RANK[worst]]
    entries = [family.place(i, s.entry) for i, s in enumerate(picked)]
    prevs = [s.prev for s in picked]
    levels = [rules_level(family, e, p) for e, p in zip(entries, prevs, strict=True)]

    status, per_object = family.checker(entries, prevs)

    assert status == worst
    assert max(levels, key=RANK.__getitem__) == worst
    if per_object is not None:
        assert per_object == levels


@pytest.mark.parametrize(("family", "deviation"), DEVIATIONS)
def test_a_named_deviation_rates_as_recorded(family, deviation):
    assert checker_level(family, deviation.entry) == deviation.checker
    assert rules_level(family, deviation.entry) == deviation.rules
    assert deviation.reason


def test_a_bit_field_cannot_be_rated_by_its_raw_number():
    """Why the sensor decodes smartctl's exit status: 0x10 is critical, 0x20 only a warning,
    and 0x30 both. No limit on the raw number rates them right; the decoding stays code."""
    raw = [_r("smartctl_status", "ge", 0x10, "critical")]
    disk = {**HDD, "smartctl_status": 0x20}

    assert checker_level(SMART, disk) == "warning"
    assert rate(raw, Reading({"smartctl_status": 0x20}, NOW))[0] == "critical"
    assert rules_level(SMART, disk) == "warning"
