# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AgentResourcesChecker.evaluate — the threshold logic run against every agent
push (CPU/RAM/disk/temperature). It decides the alert status, so the escalation
(ok → warning → critical, critical never downgraded), the >= boundary, the
pseudo-filesystem filter, and per-sensor temperature overrides are worth pinning."""

import math

import pytest

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
    assert metrics["agent_cpu_percent"] == 10


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
        "disks": [{"mount": "/", "fstype": "ext4", "percent": 90, "total_gb": 100, "used_gb": 90}],
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
    [("cpu_percent",), ("memory_percent",), ("disks", 0, "percent"), ("temperatures", 0, "temp_c")],
    ids=["cpu_percent", "memory_percent", "disk-percent", "temp_c"],
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
    assert details["disks"] == [{"mount": "/", "percent": 90, "total_gb": 100, "used_gb": 90}]
    assert details["temperatures"] == [{"sensor": "cpu", "temp_c": 85, "high": 80, "critical": 95}]
    assert_every_reader_reads(details)
