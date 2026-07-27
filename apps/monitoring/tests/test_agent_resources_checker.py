# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AgentResourcesChecker.evaluate — the threshold logic run against every agent
push (CPU/RAM/disk/temperature). It decides the alert status, so the escalation
(ok → warning → critical, critical never downgraded), the >= boundary, the
pseudo-filesystem filter, and per-sensor temperature overrides are worth pinning."""

from app.checkers.agent import AgentResourcesChecker

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
