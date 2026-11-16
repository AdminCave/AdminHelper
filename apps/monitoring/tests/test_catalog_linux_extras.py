# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules systemd-timers, needrestart, kernel, apt and unattended-upgrades (R-1234):
a marker finds each one, its check asks the agent's host sensor for its view, and each rule fires
at its threshold and not just below it."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
# Far from the test machine's clock, so only the report's own time makes a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
TWO_DAYS = 2 * 86400

MODULES = {
    "systemd-timers": ("systemd-timers.booted", "systemd_timers"),
    "needrestart": ("needrestart.bin", "needrestart"),
    "kernel": ("kernel.tainted", "kernel_taint"),
    "apt": ("apt.dpkg", "apt_state"),
    "unattended-upgrades": ("unattended-upgrades.bin", "apt_state"),
}


def _block(markers):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": [],
        "sockets": [],
        "containers": [],
        "markers": markers,
        "ports": [],
    }


def _status(module_id, **values):
    """The status the probe checker gives a result of the module's check with these values."""
    module = CATALOG.modules[module_id]
    config, why = probe_config(module, module.checks[0], module_id, {}, [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_modules_load_with_one_host_check_each():
    assert CATALOG.errors == ()
    for module_id, (_, view) in MODULES.items():
        checks = CATALOG.modules[module_id].checks
        assert [(c.sensor, c.params, c.target) for c in checks] == [("host", {"view": view}, None)]


def test_needrestart_gets_the_30_s_the_agent_gives_it():
    # The agent caps `needrestart -b` at 30 s (needrestartTimeout); the check must not cut it off
    # earlier.
    timing = {m: (c.interval, c.timeout_s) for m in MODULES for c in CATALOG.modules[m].checks}
    assert timing["needrestart"] == (3600, 30)
    assert timing["systemd-timers"][0] == 300
    assert timing["kernel"][0] == 300
    assert timing["apt"][0] == 3600
    assert timing["unattended-upgrades"][0] == 3600


def test_the_markers_are_the_paths_the_agent_reads():
    markers = {m: CATALOG.modules[m].detect.markers[0] for m in MODULES}
    assert {m: (k.paths, k.packages) for m, k in markers.items()} == {
        "systemd-timers": (["/run/systemd/system"], []),
        "needrestart": (["/usr/sbin/needrestart"], ["needrestart"]),
        "kernel": (["/proc/sys/kernel/tainted"], []),
        "apt": (["/usr/bin/dpkg"], ["dpkg"]),
        "unattended-upgrades": (["/usr/bin/unattended-upgrade"], ["unattended-upgrades"]),
    }


@pytest.mark.parametrize("module_id", sorted(MODULES))
def test_the_marker_makes_one_instance_and_its_check_binds(module_id):
    marker, view = MODULES[module_id]
    seen = match_inventory(_block({marker: True}), CATALOG)
    assert seen[(module_id, module_id)] == {"matched_by": [f"marker:{marker}"]}
    module = CATALOG.modules[module_id]
    config, why = probe_config(
        module, module.checks[0], module_id, seen[(module_id, module_id)], []
    )
    assert why is None, why
    assert config["params"] == {"view": view}


@pytest.mark.parametrize("module_id", sorted(MODULES))
@pytest.mark.parametrize("present", [None, False])
def test_without_the_marker_there_is_no_instance(module_id, present):
    marker, _ = MODULES[module_id]
    markers = {} if present is None else {marker: present}
    assert not any(m == module_id for m, _ in match_inventory(_block(markers), CATALOG))


TAINT_OK = {"tainted": 4096, "oops": False, "mce": False, "bad_page": False}


@pytest.mark.parametrize(
    ("module_id", "values", "want"),
    [
        ("systemd-timers", {"timers": 12, "failed": 0}, "ok"),
        ("systemd-timers", {"timers": 12, "failed": 1}, "warning"),
        ("needrestart", {"kernel_status": 1, "microcode_status": 1, "services": 0}, "ok"),
        # 0 is needrestart's "unknown" (a kernel it cannot compare): no alarm. The agent sends it, too,
        # where needrestart skips a check (the kernel in a container, the microcode in a VM).
        ("needrestart", {"kernel_status": 0, "microcode_status": 0, "services": 0}, "ok"),
        ("needrestart", {"kernel_status": 2, "microcode_status": 1, "services": 0}, "warning"),
        ("needrestart", {"kernel_status": 3, "microcode_status": 1, "services": 0}, "warning"),
        ("needrestart", {"kernel_status": 1, "microcode_status": 2, "services": 0}, "warning"),
        ("needrestart", {"kernel_status": 1, "microcode_status": 1, "services": 1}, "warning"),
        # A proprietary module taints (bit 12) and harms nothing.
        ("kernel", {**TAINT_OK, "livepatch_transition": 0}, "ok"),
        ("kernel", {**TAINT_OK, "oops": True, "livepatch_transition": 0}, "critical"),
        ("kernel", {**TAINT_OK, "mce": True, "livepatch_transition": 0}, "critical"),
        ("kernel", {**TAINT_OK, "bad_page": True, "livepatch_transition": 0}, "critical"),
        ("kernel", {**TAINT_OK, "livepatch_transition": 1}, "warning"),
        ("apt", {"audit": 0, "held": 3}, "ok"),
        ("apt", {"audit": 1, "held": 0}, "warning"),
        ("unattended-upgrades", {"uu_last_run_age_s": TWO_DAYS, "uu_errors": 0}, "ok"),
        ("unattended-upgrades", {"uu_last_run_age_s": TWO_DAYS + 1, "uu_errors": 0}, "warning"),
        ("unattended-upgrades", {"uu_last_run_age_s": 600, "uu_errors": 1}, "warning"),
    ],
)
def test_each_rule_fires_at_its_threshold(module_id, values, want):
    assert _status(module_id, **values) == want


def test_a_host_whose_unattended_upgrades_never_logged_is_unknown():
    # aptState sends no uu_ fields without the log: the apt module stays ok, its own module tells.
    assert _status("apt", audit=0, held=0) == "ok"
    assert _status("unattended-upgrades", audit=0, held=0) == "unknown"
