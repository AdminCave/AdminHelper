# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AgentResourcesChecker.evaluate — the threshold logic run against every agent
push (CPU/RAM/swap/load/disk/inodes/temperature). It decides the alert status, so the escalation
(ok → warning → critical, critical never downgraded), the >= boundary, the
pseudo-filesystem filter, the free-GB gate and per-mount settings of the disks, and per-sensor
temperature overrides are worth pinning."""

import math
import re
from pathlib import Path

import pytest

from app.check_configs import AgentResourcesConfig
from app.checkers import agent
from app.checkers.agent import AgentResourcesChecker

from ._helpers import assert_every_reader_reads

CHECKER = AgentResourcesChecker()
T = {
    "cpu_warn": 80,
    "cpu_crit": 95,
    "memory_warn": 80,
    "memory_crit": 95,
    "disk_warn": 85,
    "disk_crit": 95,
}


def _report(**resources):
    return {"resources": resources}


def test_empty_resources_is_unknown():
    assert CHECKER.evaluate(T, {"resources": {}})[0] == "unknown"


def test_all_below_warn_is_ok():
    status, _msg, metrics = CHECKER.evaluate(T, _report(cpu_percent=10, memory_percent=20))
    assert status == "ok"
    # Graded, not written: the push handler writes CPU and RAM per server (R-0633).
    assert set(metrics) == {"_details"}
    assert (metrics["_details"]["cpu"], metrics["_details"]["memory"]) == (10, 20)


def test_cpu_exactly_at_warn_is_warning():
    assert CHECKER.evaluate(T, _report(cpu_percent=80, memory_percent=5))[0] == "warning"


def test_cpu_just_below_warn_is_ok():
    assert CHECKER.evaluate(T, _report(cpu_percent=79.9))[0] == "ok"


def test_cpu_exactly_at_crit_is_critical():
    assert CHECKER.evaluate(T, _report(cpu_percent=95))[0] == "critical"


def test_critical_is_not_downgraded_by_a_later_warning():
    # CPU critical + RAM warning -> overall stays critical, message lists both.
    status, msg, _ = CHECKER.evaluate(T, _report(cpu_percent=99, memory_percent=85))
    assert status == "critical"
    assert "CPU" in msg and "RAM" in msg


def test_pseudo_filesystems_are_filtered_out():
    report = _report(
        disks=[
            {"mount": "/tmp", "fstype": "tmpfs", "percent": 99},  # excluded
            {"mount": "/", "fstype": "ext4", "percent": 99},  # real, over crit
        ]
    )
    status, msg, _ = CHECKER.evaluate(T, report)
    assert status == "critical"
    assert "Disk /" in msg
    assert "Disk /tmp" not in msg  # excluded fstype is never graded


def test_per_sensor_temperature_override_lowers_the_threshold():
    report = _report(temperatures=[{"sensor": "cpu", "temp_c": 70}])
    cfg = {**T, "temp_warn": 80, "temp_crit": 95, "temp_overrides": {"cpu": {"crit": 65}}}
    # 70 is below the default crit (95) but >= the per-sensor override (65).
    assert CHECKER.evaluate(cfg, report)[0] == "critical"


class TestHysteresis:
    """Per-metric entry/release hysteresis (T6): once a metric is warning or
    critical, its thresholds drop by hysteresis_pp (default 10) until the value
    clears the release band. Memory travels via _details["problems"]."""

    CFG = {"cpu_warn": 90, "cpu_crit": 95}

    def test_release_band_keeps_warning(self):
        prev = {"problems": {"cpu": "warning"}}
        status, _msg, _m = CHECKER.evaluate(self.CFG, _report(cpu_percent=84), prev)
        assert status == "warning"

    def test_below_release_band_recovers(self):
        prev = {"problems": {"cpu": "warning"}}
        status, _msg, _m = CHECKER.evaluate(self.CFG, _report(cpu_percent=79), prev)
        assert status == "ok"

    def test_without_previous_problem_entry_threshold_applies(self):
        status, _msg, _m = CHECKER.evaluate(self.CFG, _report(cpu_percent=84), None)
        assert status == "ok"

    def test_hysteresis_pp_zero_disables(self):
        cfg = {**self.CFG, "hysteresis_pp": 0}
        prev = {"problems": {"cpu": "warning"}}
        status, _msg, _m = CHECKER.evaluate(cfg, _report(cpu_percent=84), prev)
        assert status == "ok"

    def test_warning_metric_never_escalates_via_lowered_crit(self):
        # 92 was warning last round; the lowered crit (95-10=85) must NOT apply —
        # only a previously-critical metric gets the crit release.
        prev = {"problems": {"cpu": "warning"}}
        status, _msg, _m = CHECKER.evaluate(self.CFG, _report(cpu_percent=92), prev)
        assert status == "warning"

    def test_critical_metric_keeps_critical_in_release_band(self):
        prev = {"problems": {"cpu": "critical"}}
        status, _msg, _m = CHECKER.evaluate(self.CFG, _report(cpu_percent=92), prev)
        assert status == "critical"

    def test_hysteresis_is_per_metric_not_per_check(self):
        # CPU was warning; a disk idling just below its entry threshold must not
        # be dragged into the release band by the CPU's state.
        cfg = {**self.CFG, "disk_warn": 80, "disk_crit": 90}
        prev = {"problems": {"cpu": "warning"}}
        report = _report(
            cpu_percent=50,
            disks=[{"mount": "/", "percent": 79, "fstype": "ext4"}],
        )
        status, _msg, _m = CHECKER.evaluate(cfg, report, prev)
        assert status == "ok"

    def test_problems_map_is_written_to_details(self):
        _status, _msg, m = CHECKER.evaluate(self.CFG, _report(cpu_percent=92), None)
        assert m["_details"]["problems"] == {"cpu": "warning"}
        _status, _msg, m = CHECKER.evaluate(self.CFG, _report(cpu_percent=50), None)
        assert m["_details"]["problems"] == {}


# --- Swap, inodes and load per CPU (agent report v3) ---
_SWAP = {"swap_total_mb": 2048}


def _inodes(value, mount="/"):
    return {"disks": [{"mount": mount, "fstype": "ext4", "percent": 10, "inodes_percent": value}]}


def _load(load_5m, cpu_count=8):
    return {"load_5m": load_5m, "cpu_count": cpu_count}


@pytest.mark.parametrize(
    ("resources", "status", "message"),
    [
        pytest.param({**_SWAP, "swap_percent": 79.9}, "ok", "OK", id="swap-below-warn"),
        pytest.param(
            {**_SWAP, "swap_percent": 80}, "warning", "Swap 80% (>=80%)", id="swap-at-warn"
        ),
        pytest.param(
            {**_SWAP, "swap_percent": 94.9}, "warning", "Swap 94.9% (>=80%)", id="swap-above-warn"
        ),
        pytest.param(
            {**_SWAP, "swap_percent": 95}, "critical", "Swap 95% (>=95%)", id="swap-at-crit"
        ),
        pytest.param(
            {**_SWAP, "swap_percent": 99}, "critical", "Swap 99% (>=95%)", id="swap-above-crit"
        ),
        pytest.param(_inodes(79.9), "ok", "OK", id="inodes-below-warn"),
        pytest.param(_inodes(80), "warning", "Inodes / 80% (>=80%)", id="inodes-at-warn"),
        pytest.param(_inodes(89.9), "warning", "Inodes / 89.9% (>=80%)", id="inodes-above-warn"),
        pytest.param(_inodes(90), "critical", "Inodes / 90% (>=90%)", id="inodes-at-crit"),
        pytest.param(_inodes(99), "critical", "Inodes / 99% (>=90%)", id="inodes-above-crit"),
        # 11.9 / 8 = 1.4875, rounded to 1.49.
        pytest.param(_load(11.9), "ok", "OK", id="load-below-warn"),
        pytest.param(_load(12), "warning", "Load 1.5/CPU (>=1.5/CPU)", id="load-at-warn"),
        # 11.97 / 8 = 1.49625: rounded to 1.5 before grading, so it is graded as shown.
        pytest.param(
            _load(11.97), "warning", "Load 1.5/CPU (>=1.5/CPU)", id="load-rounded-up-to-warn"
        ),
        pytest.param(_load(20), "warning", "Load 2.5/CPU (>=1.5/CPU)", id="load-above-warn"),
        pytest.param(_load(24), "critical", "Load 3.0/CPU (>=3.0/CPU)", id="load-at-crit"),
        pytest.param(_load(32), "critical", "Load 4.0/CPU (>=3.0/CPU)", id="load-above-crit"),
    ],
)
def test_new_metric_against_the_default_thresholds(resources, status, message):
    got_status, got_message, _metrics = CHECKER.evaluate({}, {"resources": resources})
    assert (got_status, got_message) == (status, message)


@pytest.mark.parametrize(
    ("config", "resources", "message"),
    [
        pytest.param(
            {"swap_warn": 50, "swap_crit": 60},
            {**_SWAP, "swap_percent": 55},
            "Swap 55% (>=50%)",
            id="swap",
        ),
        pytest.param(
            {"inode_warn": 50, "inode_crit": 60}, _inodes(55), "Inodes / 55% (>=50%)", id="inodes"
        ),
        pytest.param(
            {"load_warn": 0.5, "load_crit": 1}, _load(6), "Load 0.75/CPU (>=0.5/CPU)", id="load"
        ),
    ],
)
def test_new_metric_follows_its_configured_thresholds(config, resources, message):
    assert CHECKER.evaluate(config, {"resources": resources})[:2] == ("warning", message)


# One report per new metric at each default threshold and just below it.
_AT_THE_DEFAULTS = [
    *({**_SWAP, "swap_percent": v} for v in (79.9, 80, 94.9, 95)),
    *(_inodes(v) for v in (79.9, 80, 89.9, 90)),
    *(_load(v) for v in (11.9, 12, 23.9, 24)),
    # The free-GB gate of a disk at the percentage warning threshold.
    *({"disks": [{"mount": "/", "percent": 85, "free_gb": v}]} for v in (19.9, 20)),
]


def test_checker_defaults_are_the_config_defaults():
    # A check stored without the keys is rated as the config schema documents them.
    defaults = AgentResourcesConfig().model_dump()
    for resources in _AT_THE_DEFAULTS:
        report = {"resources": resources}
        assert CHECKER.evaluate({}, report) == CHECKER.evaluate(defaults, report)


@pytest.mark.parametrize(
    "resources",
    [
        pytest.param({"swap_percent": 99, "swap_total_mb": 0}, id="swap-total-0"),
        pytest.param({"swap_percent": 99}, id="swap-total-missing"),
        pytest.param({"swap_percent": 99, "swap_total_mb": "2048"}, id="swap-total-str"),
    ],
)
def test_swap_without_a_swap_device_is_not_rated(resources):
    status, message, metrics = CHECKER.evaluate({}, {"resources": resources})
    assert (status, message, metrics["_details"]["problems"]) == ("ok", "OK", {})


@pytest.mark.parametrize(
    "cpu_count",
    [0, -1, True, "8", 8.5, 8.0, None, [8]],
    ids=["0", "-1", "true", "str", "8.5", "8.0", "null", "list"],
)
def test_load_without_a_whole_cpu_count_of_at_least_one_is_not_rated(cpu_count):
    status, message, metrics = CHECKER.evaluate({}, {"resources": _load(100, cpu_count)})
    assert (status, message, metrics["_details"]["problems"]) == ("ok", "OK", {})
    assert (metrics["_details"]["cpu_count"], metrics["_details"]["load_per_cpu"]) == (None, None)


def test_load_without_load_5m_is_not_rated():
    # load_1m and load_15m never count: the load per CPU is load_5m / cpu_count.
    resources = {"cpu_count": 1, "load_1m": 100, "load_15m": 100}
    status, message, metrics = CHECKER.evaluate({}, {"resources": resources})
    assert (status, message, metrics["_details"]["problems"]) == ("ok", "OK", {})
    assert (metrics["_details"]["cpu_count"], metrics["_details"]["load_per_cpu"]) == (1, None)


def test_a_report_without_the_new_fields_is_rated_as_before():
    # An agent before report v3: load without cpu_count, no swap, no inodes, no free GB.
    # Status and message are those the checker gave before swap, inodes, load and the
    # free-GB gate; _details only gains the new keys, empty (no disk ignored). No CPU/RAM
    # values next to _details: the push handler writes them per server (R-0633).
    report = _report(
        cpu_percent=12.5,
        memory_percent=83,
        memory_total_mb=16000,
        memory_used_mb=13280,
        load_1m=40.0,
        load_5m=40.0,
        load_15m=40.0,
        disks=[{"mount": "/", "fstype": "ext4", "percent": 91, "total_gb": 100, "used_gb": 91}],
        temperatures=[{"sensor": "cpu", "temp_c": 50, "high": 80, "critical": 95}],
    )
    status, message, metrics = CHECKER.evaluate({}, report, {"problems": {"memory": "warning"}})
    assert (status, message) == ("warning", "RAM 83% (>=80%); Disk / 91% (>=85%)")
    assert metrics == {
        "_details": {
            "cpu": 12.5,
            "memory": 83,
            "problems": {"memory": "warning", "disk:/": "warning"},
            "memory_total_mb": 16000,
            "memory_used_mb": 13280,
            "swap": None,
            "swap_total_mb": None,
            "swap_used_mb": None,
            "cpu_count": None,
            "load_per_cpu": None,
            "disks": [
                {
                    "mount": "/",
                    "percent": 91,
                    "total_gb": 100,
                    "used_gb": 91,
                    "free_gb": None,
                    "inodes_percent": None,
                    "ignored": False,
                }
            ],
            "temperatures": [{"sensor": "cpu", "temp_c": 50, "high": 80, "critical": 95}],
        },
    }


class TestNewMetricHysteresis:
    """Swap and inodes keep the release band of the other percentages; the load has
    none (hysteresis_pp is in percentage points, the load per CPU is no percentage)."""

    def test_swap_release_band_keeps_warning(self):
        prev = {"problems": {"swap": "warning"}}
        report = {"resources": {**_SWAP, "swap_percent": 75}}
        assert CHECKER.evaluate({}, report, prev)[0] == "warning"

    def test_swap_below_release_band_recovers(self):
        prev = {"problems": {"swap": "warning"}}
        report = {"resources": {**_SWAP, "swap_percent": 69}}
        assert CHECKER.evaluate({}, report, prev)[0] == "ok"

    def test_swap_critical_keeps_critical_in_release_band(self):
        prev = {"problems": {"swap": "critical"}}
        report = {"resources": {**_SWAP, "swap_percent": 90}}
        assert CHECKER.evaluate({}, report, prev)[0] == "critical"

    def test_inodes_release_band_keeps_warning(self):
        prev = {"problems": {"inode:/": "warning"}}
        assert CHECKER.evaluate({}, {"resources": _inodes(75)}, prev)[0] == "warning"

    def test_inodes_below_release_band_recovers(self):
        prev = {"problems": {"inode:/": "warning"}}
        assert CHECKER.evaluate({}, {"resources": _inodes(69)}, prev)[0] == "ok"

    def test_inodes_hysteresis_is_per_mount_and_apart_from_the_disk(self):
        # Neither another mount's inodes nor the same mount's usage lower the
        # thresholds of the inodes of /.
        prev = {"problems": {"inode:/data": "warning", "disk:/": "warning"}}
        assert CHECKER.evaluate({}, {"resources": _inodes(75)}, prev)[0] == "ok"

    @pytest.mark.parametrize("prev_level", ["warning", "critical"])
    def test_load_has_no_release_band(self, prev_level):
        # 1.49/CPU is below the warning threshold of 1.5, whatever the last round said.
        prev = {"problems": {"load": prev_level}}
        assert CHECKER.evaluate({}, {"resources": _load(11.9)}, prev)[0] == "ok"

    def test_critical_load_is_warning_below_the_critical_threshold(self):
        prev = {"problems": {"load": "critical"}}
        assert CHECKER.evaluate({}, {"resources": _load(23.9)}, prev)[0] == "warning"

    def test_new_metrics_are_written_to_the_problems_map(self):
        resources = {
            **_SWAP,
            "swap_percent": 85,
            **_load(24),
            **_inodes(95, mount="/var"),
        }
        _status, _msg, m = CHECKER.evaluate({}, {"resources": resources})
        assert m["_details"]["problems"] == {
            "swap": "warning",
            "load": "critical",
            "inode:/var": "critical",
        }


# --- Load per CPU in a container (T31) ---
# 32 / 8 = 4.0/CPU, above the critical threshold of 3.0.
_HIGH_LOAD = _load(32)
_RATED_HIGH_LOAD = ("critical", "Load 4.0/CPU (>=3.0/CPU)")


def _host(system, role="guest"):
    return {"os": "linux", "virtualization": {"system": system, "role": role}}


@pytest.mark.parametrize("system", ["lxc", "docker", "openvz", "rkt"])
def test_the_load_of_a_container_is_shown_but_not_rated(system):
    report = {"host": _host(system), "resources": _HIGH_LOAD}
    # Last round's load problem does not count either.
    status, message, metrics = CHECKER.evaluate({}, report, {"problems": {"load": "critical"}})
    assert (status, message) == ("ok", "OK")
    details = metrics["_details"]
    assert details["problems"] == {}
    assert (details["cpu_count"], details["load_per_cpu"], details["load_rated"]) == (8, 4.0, False)
    assert_every_reader_reads(details)


def test_a_container_still_rates_everything_but_the_load():
    resources = {**_HIGH_LOAD, **_SWAP, "swap_percent": 85, "cpu_percent": 99}
    status, message, metrics = CHECKER.evaluate({}, {"host": _host("lxc"), "resources": resources})
    assert (status, message) == ("critical", "CPU 99% (>=95%); Swap 85% (>=80%)")
    assert metrics["_details"]["problems"] == {"cpu": "critical", "swap": "warning"}


@pytest.mark.parametrize(
    "host",
    [
        pytest.param(_host("kvm"), id="kvm-guest"),
        pytest.param(_host("xen"), id="xen-guest"),
        pytest.param(_host("hyperv"), id="hyperv-guest"),
        pytest.param(_host("kvm", "host"), id="kvm-host"),
        pytest.param(_host("lxc", "host"), id="lxc-host"),
        pytest.param(_host("linux-vserver"), id="system-not-in-the-list"),
        pytest.param(_host("", ""), id="bare-metal"),
        pytest.param({"os": "linux"}, id="without-virtualization"),
        # What a broken agent can send: rated as without the host facts, nothing raises.
        pytest.param({"virtualization": ["lxc", "guest"]}, id="virtualization-list"),
        pytest.param(_host(["lxc"]), id="system-list"),
        pytest.param(_host({"lxc": 1}), id="system-object"),
        pytest.param(_host("lxc", ["guest"]), id="role-list"),
        pytest.param(["lxc"], id="host-list"),
        pytest.param("lxc", id="host-str"),
    ],
)
def test_the_load_of_a_host_or_vm_is_rated_as_before(host):
    report = {"host": host, "resources": _HIGH_LOAD}
    assert CHECKER.evaluate({}, report) == CHECKER.evaluate({}, {"resources": _HIGH_LOAD})
    status, message, metrics = CHECKER.evaluate({}, report)
    assert (status, message) == _RATED_HIGH_LOAD
    assert metrics["_details"]["problems"] == {"load": "critical"}
    assert "load_rated" not in metrics["_details"]


def test_a_report_without_host_facts_rates_the_load_as_before():
    status, message, metrics = CHECKER.evaluate({}, {"resources": _HIGH_LOAD})
    assert (status, message) == _RATED_HIGH_LOAD
    assert metrics["_details"]["problems"] == {"load": "critical"}
    assert "load_rated" not in metrics["_details"]


_AGENT_SYSTEM = Path(__file__).resolve().parents[3] / "apps/agent/internal/monitor/system_linux.go"
_GO_CONTAINER_SYSTEMS = re.compile(r"var containerSystems = map\[string\]bool\{(.*?)\}", re.S)


def test_container_systems_match_the_agent():
    # The agent counts the OOM kills of a container from its cgroup with the same list
    # (T30). If a system is added on one side only, the agent and the checker disagree
    # on what a container is, and nothing else turns red.
    m = _GO_CONTAINER_SYSTEMS.search(_AGENT_SYSTEM.read_text(encoding="utf-8"))
    assert m, f"containerSystems not found in {_AGENT_SYSTEM}"
    agent_systems = re.findall(r'"([a-z-]+)": true', m.group(1))
    # Sanity: the scan parsed entries instead of matching empty.
    assert "lxc" in agent_systems
    assert sorted(agent_systems) == sorted(agent._CONTAINER_SYSTEMS)


# --- Disks: free-GB gate, thresholds per mount and ignored mounts (agent report v3) ---
def _disk(percent, free_gb=None, mount="/", **extra):
    disk = {"mount": mount, "fstype": "ext4", "percent": percent, **extra}
    if free_gb is not None:
        disk["free_gb"] = free_gb
    return disk


def _disks(*disks):
    return {"resources": {"disks": list(disks)}}


@pytest.mark.parametrize(
    ("config", "disk", "status", "message"),
    [
        pytest.param({}, _disk(85, 600), "ok", "OK", id="600-gb-free"),
        pytest.param(
            {}, _disk(85, 15), "warning", "Disk / 85%, 15 GB free (>=85%)", id="15-gb-free"
        ),
        pytest.param(
            {}, _disk(95, 15), "critical", "Disk / 95%, 15 GB free (>=95%)", id="15-gb-free-crit"
        ),
        pytest.param(
            {}, _disk(85, 19.9), "warning", "Disk / 85%, 19.9 GB free (>=85%)", id="below-the-gate"
        ),
        pytest.param({}, _disk(85, 20), "ok", "OK", id="at-the-gate"),
        pytest.param({}, _disk(84.9, 5), "ok", "OK", id="below-the-gate-and-below-warn"),
        pytest.param(
            {}, _disk(85), "warning", "Disk / 85% (>=85%)", id="older-agent-without-free-gb"
        ),
        pytest.param(
            {"disk_min_free_gb": 0},
            _disk(85, 600),
            "warning",
            "Disk / 85%, 600 GB free (>=85%)",
            id="gate-off",
        ),
        pytest.param(
            {"disk_min_free_gb": 1000},
            _disk(85, 600),
            "warning",
            "Disk / 85%, 600 GB free (>=85%)",
            id="higher-gate",
        ),
    ],
)
def test_the_percentage_alarm_counts_only_below_the_minimum_free_gb(config, disk, status, message):
    assert CHECKER.evaluate(config, _disks(disk))[:2] == (status, message)


def test_the_gate_leaves_the_inodes_rated():
    status, message, _ = CHECKER.evaluate({}, _disks(_disk(85, 600, inodes_percent=95)))
    assert (status, message) == ("critical", "Inodes / 95% (>=90%)")


_OVERRIDES = {"/data": {"warn": 90, "crit": 98, "min_free_gb": 1000}}


@pytest.mark.parametrize(
    ("disk", "status", "message"),
    [
        pytest.param(_disk(89.9, 600, "/data"), "ok", "OK", id="below-the-mount-warn"),
        pytest.param(
            _disk(90, 600, "/data"),
            "warning",
            "Disk /data 90%, 600 GB free (>=90%)",
            id="at-the-mount-warn",
        ),
        pytest.param(
            _disk(97.9, 600, "/data"),
            "warning",
            "Disk /data 97.9%, 600 GB free (>=90%)",
            id="below-the-mount-crit",
        ),
        pytest.param(
            _disk(98, 600, "/data"),
            "critical",
            "Disk /data 98%, 600 GB free (>=98%)",
            id="at-the-mount-crit",
        ),
        pytest.param(_disk(98, 1000, "/data"), "ok", "OK", id="at-the-mount-gate"),
        # Every other mount keeps the global settings.
        pytest.param(_disk(90, 600, "/"), "ok", "OK", id="other-mount-global-gate"),
        pytest.param(
            _disk(85, 15, "/"),
            "warning",
            "Disk / 85%, 15 GB free (>=85%)",
            id="other-mount-global-warn",
        ),
    ],
)
def test_thresholds_and_minimum_free_gb_per_mount(disk, status, message):
    config = {"disk_overrides": _OVERRIDES}
    assert CHECKER.evaluate(config, _disks(disk))[:2] == (status, message)


@pytest.mark.parametrize(
    ("override", "disk", "status", "message"),
    [
        pytest.param(
            {"min_free_gb": 0},
            _disk(85, 600, "/data"),
            "warning",
            "Disk /data 85%, 600 GB free (>=85%)",
            id="only-the-gate-off",
        ),
        pytest.param({"warn": 70}, _disk(75, 600, "/data"), "ok", "OK", id="only-warn-gated"),
        pytest.param(
            {"warn": 70},
            _disk(75, 15, "/data"),
            "warning",
            "Disk /data 75%, 15 GB free (>=70%)",
            id="only-warn",
        ),
    ],
)
def test_an_override_without_a_key_takes_the_global_setting(override, disk, status, message):
    config = {"disk_overrides": {"/data": override}}
    assert CHECKER.evaluate(config, _disks(disk))[:2] == (status, message)


@pytest.mark.parametrize(
    "disk", [_disk(85, 15), _disk(85, 600), _disk(95, 15)], ids=["warn", "gated", "crit"]
)
def test_an_override_key_stored_as_null_counts_as_unset(disk):
    # The config schema takes null for each key of an override.
    config = {"disk_overrides": {"/": {"warn": None, "crit": None, "min_free_gb": None}}}
    assert CHECKER.evaluate(config, _disks(disk)) == CHECKER.evaluate({}, _disks(disk))


def test_an_ignored_mount_is_rated_neither_on_usage_nor_on_inodes():
    report = _disks(
        _disk(99, 0.1, "/boot/efi", inodes_percent=99, total_gb=0.5, used_gb=0.4),
        _disk(10, 50, "/", inodes_percent=10),
    )
    # Without ignore_mounts the same report is critical on both.
    assert CHECKER.evaluate({}, report)[:2] == (
        "critical",
        "Disk /boot/efi 99%, 0.1 GB free (>=95%); Inodes /boot/efi 99% (>=90%)",
    )
    # Last round's levels of the mount do not count either.
    prev = {"problems": {"disk:/boot/efi": "critical", "inode:/boot/efi": "critical"}}
    status, message, metrics = CHECKER.evaluate({"ignore_mounts": ["/boot/efi"]}, report, prev)
    assert (status, message, metrics["_details"]["problems"]) == ("ok", "OK", {})
    # Still listed in _details, marked.
    assert metrics["_details"]["disks"] == [
        {
            "mount": "/boot/efi",
            "percent": 99,
            "total_gb": 0.5,
            "used_gb": 0.4,
            "free_gb": 0.1,
            "inodes_percent": 99,
            "ignored": True,
        },
        {
            "mount": "/",
            "percent": 10,
            "total_gb": None,
            "used_gb": None,
            "free_gb": 50,
            "inodes_percent": 10,
            "ignored": False,
        },
    ]


@pytest.mark.parametrize("ignored", ["/boot", "/boot/", "/boot/*", "/BOOT/EFI", "/boot/efi "])
def test_ignore_mounts_takes_exact_paths_only(ignored):
    report = _disks(_disk(99, 0.1, "/boot/efi"))
    status, _msg, metrics = CHECKER.evaluate({"ignore_mounts": [ignored]}, report)
    assert status == "critical"
    assert metrics["_details"]["disks"][0]["ignored"] is False


def test_a_disk_without_mount_is_graded_listed_and_ignored_under_one_name():
    # The desktop rates a listed disk by problems["disk:<mount>"], so _details must carry
    # the name it was graded under, not the root's rating of a real "/" next to it.
    report = _disks({"fstype": "ext4", "percent": 99, "inodes_percent": 95}, _disk(10))
    status, message, metrics = CHECKER.evaluate({}, report)
    assert (status, message) == ("critical", "Disk ? 99% (>=95%); Inodes ? 95% (>=90%)")
    details = metrics["_details"]
    assert details["problems"] == {"disk:?": "critical", "inode:?": "critical"}
    assert [(d["mount"], d["ignored"]) for d in details["disks"]] == [("?", False), ("/", False)]

    status, message, metrics = CHECKER.evaluate({"ignore_mounts": ["?"]}, report)
    details = metrics["_details"]
    assert (status, message, details["problems"]) == ("ok", "OK", {})
    assert [(d["mount"], d["ignored"]) for d in details["disks"]] == [("?", True), ("/", False)]


class TestDiskGateHysteresis:
    """The gate decides whether a disk's percentage is graded at all; its release band
    applies only while it is graded."""

    def test_warning_disk_whose_free_gb_rise_above_the_gate_is_ok(self):
        prev = {"problems": {"disk:/": "warning"}}
        status, message, metrics = CHECKER.evaluate({}, _disks(_disk(86, 25)), prev)
        assert (status, message, metrics["_details"]["problems"]) == ("ok", "OK", {})

    def test_warning_disk_below_the_gate_keeps_its_release_band(self):
        # 80 % is below the entry threshold 85, in the release band down to 75.
        prev = {"problems": {"disk:/": "warning"}}
        status, message, _ = CHECKER.evaluate({}, _disks(_disk(80, 15)), prev)
        assert (status, message) == ("warning", "Disk / 80%, 15 GB free (>=85%)")

    def test_back_below_the_gate_the_entry_threshold_applies(self):
        # The gated round remembered no level for the disk, so 80 % no longer holds it.
        prev = {"problems": {"disk:/": "warning"}}
        _status, _msg, metrics = CHECKER.evaluate({}, _disks(_disk(86, 25)), prev)
        assert CHECKER.evaluate({}, _disks(_disk(80, 15)), metrics["_details"])[0] == "ok"


# --- R-0517: a field of the wrong JSON type counts as missing ---
# What a broken or hijacked agent can put where a number belongs. A regular agent sends
# numbers; before R-0517 each of these raised in evaluate (the check froze on its old
# state) or went raw into status and message ("CPU inf%", a 400-digit critical).
_BIG_INT = 10**400  # beyond float range: math.isfinite raises OverflowError on it
_NOT_NUMBERS = [
    pytest.param("85", id="numeric-str"),
    pytest.param("abc", id="str"),
    pytest.param([1], id="list"),
    pytest.param({}, id="dict"),
    pytest.param(True, id="bool"),
    pytest.param(None, id="null"),
    pytest.param(math.nan, id="nan"),
    pytest.param(math.inf, id="inf"),
    pytest.param(-math.inf, id="-inf"),
    pytest.param(_BIG_INT, id="int-400-digits"),
]


@pytest.mark.parametrize("value", [42, 1.5, 0, -3, 0.0, 1e308])
def test_agent_number_returns_a_json_number_unchanged(value):
    assert agent.agent_number(value) is value


@pytest.mark.parametrize("value", [*_NOT_NUMBERS, pytest.param(False, id="false")])
def test_agent_number_is_none_for_anything_else(value):
    assert agent.agent_number(value) is None


def _resources() -> dict:
    """Every rated field and every number of _details set, so dropping one still leaves
    resources to rate."""
    return {
        "cpu_percent": 90,
        "memory_percent": 85,
        "memory_total_mb": 16000,
        "memory_used_mb": 13600,
        "swap_percent": 85,
        "swap_total_mb": 2048,
        "swap_used_mb": 1741,
        "cpu_count": 8,
        "load_5m": 16,
        "disks": [
            {
                "mount": "/",
                "fstype": "ext4",
                "percent": 90,
                "total_gb": 100,
                "used_gb": 90,
                "free_gb": 10,
                "inodes_percent": 85,
            }
        ],
        "temperatures": [{"sensor": "cpu", "temp_c": 85, "high": 80, "critical": 95}],
    }


def _with(path: tuple, value: object) -> dict:
    resources = _resources()
    target = resources
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return resources


def _without(path: tuple) -> dict:
    resources = _resources()
    target = resources
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return resources


@pytest.mark.parametrize("value", _NOT_NUMBERS)
@pytest.mark.parametrize(
    "path",
    [
        ("cpu_percent",),
        ("memory_percent",),
        ("swap_percent",),
        ("swap_total_mb",),
        ("cpu_count",),
        ("load_5m",),
        ("disks", 0, "percent"),
        ("disks", 0, "free_gb"),
        ("disks", 0, "inodes_percent"),
        ("temperatures", 0, "temp_c"),
    ],
    ids=[
        "cpu_percent",
        "memory_percent",
        "swap_percent",
        "swap_total_mb",
        "cpu_count",
        "load_5m",
        "disk-percent",
        "free_gb",
        "inodes_percent",
        "temp_c",
    ],
)
def test_a_number_field_that_is_no_json_number_counts_as_missing(path, value):
    broken = CHECKER.evaluate(T, {"resources": _with(path, value)})
    assert broken == CHECKER.evaluate(T, {"resources": _without(path)})


@pytest.mark.parametrize("value", [[1], {"a": 1}, 7, None], ids=["list", "dict", "int", "null"])
@pytest.mark.parametrize(
    "path",
    [("disks", 0, "fstype"), ("disks", 0, "mount"), ("temperatures", 0, "sensor")],
    ids=["fstype", "mount", "sensor"],
)
def test_a_text_field_that_is_no_string_counts_as_missing(path, value):
    broken = CHECKER.evaluate(T, {"resources": _with(path, value)})
    assert broken == CHECKER.evaluate(T, {"resources": _without(path)})


@pytest.mark.parametrize(
    "resources", [[{"cpu_percent": 99}], "abc", 42, True], ids=["list", "str", "int", "bool"]
)
def test_resources_that_is_no_object_counts_as_missing(resources):
    assert CHECKER.evaluate(T, {"resources": resources}) == ("unknown", "No resource data", None)


@pytest.mark.parametrize("value", [{"mount": "/", "sensor": "cpu"}, "abc"], ids=["dict", "str"])
@pytest.mark.parametrize("key", ["disks", "temperatures"])
def test_a_disk_or_sensor_list_that_is_no_list_counts_as_missing(key, value):
    broken = CHECKER.evaluate(T, {"resources": _with((key,), value)})
    assert broken == CHECKER.evaluate(T, {"resources": _without((key,))})


def test_a_disk_entry_that_is_no_object_is_skipped_and_the_valid_one_counts():
    report = _report(disks=["x", {"mount": "/", "fstype": "ext4", "percent": 99}])
    status, msg, metrics = CHECKER.evaluate(T, report)
    assert (status, msg) == ("critical", "Disk / 99% (>=95%)")
    assert [d["mount"] for d in metrics["_details"]["disks"]] == ["/"]


def test_a_sensor_entry_that_is_no_object_is_skipped_and_the_valid_one_counts():
    report = _report(temperatures=["x", {"sensor": "cpu", "temp_c": 99}])
    status, msg, metrics = CHECKER.evaluate(T, report)
    assert (status, msg) == ("critical", "Temp cpu 99°C (>=95°C)")
    assert [s["sensor"] for s in metrics["_details"]["temperatures"]] == ["cpu"]


def test_at_most_500_disks_and_sensors_are_rated():
    # The entries past the cap are neither graded (the last one would be critical) nor listed.
    disks = [{"mount": f"/m{i}", "fstype": "ext4", "percent": 1} for i in range(2000)]
    disks[-1]["percent"] = 99
    sensors = [{"sensor": f"s{i}", "temp_c": 1} for i in range(2000)]
    sensors[-1]["temp_c"] = 99
    status, _msg, metrics = CHECKER.evaluate(T, _report(disks=disks, temperatures=sensors))
    assert status == "ok"
    assert len(metrics["_details"]["disks"]) == 500
    assert len(metrics["_details"]["temperatures"]) == 500


# --- Numbers that only go into _details ---
# _details goes as it is into the answers of GET /status and GET /checks, which the desktop reads
# as a whole: NaN there fails the answer (JSONResponse writes with allow_nan=False), and a 400-digit
# integer is no number every JSON reader takes. The RAM sums, disk sizes and sensor limits count
# only as a JSON number, like the rated fields; anything else shows as without the field, null for
# the RAM sums and disk sizes, 0 for the sensor limits.
_DETAIL_NUMBERS = [
    pytest.param(("memory_total_mb",), None, id="memory_total_mb"),
    pytest.param(("memory_used_mb",), None, id="memory_used_mb"),
    pytest.param(("swap_used_mb",), None, id="swap_used_mb"),
    pytest.param(("disks", 0, "total_gb"), None, id="total_gb"),
    pytest.param(("disks", 0, "used_gb"), None, id="used_gb"),
    pytest.param(("temperatures", 0, "high"), 0, id="high"),
    pytest.param(("temperatures", 0, "critical"), 0, id="critical"),
]


def _detail(details: dict, path: tuple):
    """The value at path in _details, which nests these fields as resources does."""
    for key in path:
        details = details[key]
    return details


def _without_details(metrics: dict) -> dict:
    return {key: value for key, value in metrics.items() if key != "_details"}


@pytest.mark.parametrize("value", _NOT_NUMBERS)
@pytest.mark.parametrize(("path", "shown"), _DETAIL_NUMBERS)
def test_a_detail_number_that_is_no_json_number_shows_as_without_the_field(path, shown, value):
    status, msg, metrics = CHECKER.evaluate(T, {"resources": _with(path, value)})
    assert (status, msg, metrics) == CHECKER.evaluate(T, {"resources": _without(path)})
    assert _detail(metrics["_details"], path) == shown
    # Only _details changes: status, message and metrics are those of the regular report.
    regular_status, regular_msg, regular = CHECKER.evaluate(T, {"resources": _resources()})
    assert (status, msg) == (regular_status, regular_msg)
    assert _without_details(metrics) == _without_details(regular)
    assert_every_reader_reads(metrics["_details"])


def test_detail_numbers_of_a_regular_report():
    _status, _msg, metrics = CHECKER.evaluate(T, {"resources": _resources()})
    details = metrics["_details"]
    assert (details["memory_total_mb"], details["memory_used_mb"]) == (16000, 13600)
    assert (details["swap"], details["swap_total_mb"], details["swap_used_mb"]) == (85, 2048, 1741)
    assert (details["cpu_count"], details["load_per_cpu"]) == (8, 2.0)
    assert details["disks"] == [
        {
            "mount": "/",
            "percent": 90,
            "total_gb": 100,
            "used_gb": 90,
            "free_gb": 10,
            "inodes_percent": 85,
            "ignored": False,
        }
    ]
    assert details["temperatures"] == [{"sensor": "cpu", "temp_c": 85, "high": 80, "critical": 95}]
    assert_every_reader_reads(details)
