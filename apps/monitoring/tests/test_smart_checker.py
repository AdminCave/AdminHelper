# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SmartHealthChecker.evaluate — disk-health alerting. Focused on the bug-prone
bits: missing SMART data is NOT an error (VMs), a failed/uncorrectable disk is
critical, the smartctl exit-code bit flags map to the right severity, the
temperature threshold depends on the disk kind, and an ignored device is
skipped. (ATA/SATA disks only, to stay clear of the NVMe-spare specifics.)"""

from app.checkers.smart import SmartHealthChecker

CHECKER = SmartHealthChecker()


def _disk(**kw):
    # A clean ATA disk by default: passes, no errors, cool.
    return {
        "device": "/dev/sda",
        "model": "X",
        "protocol": "ATA",
        "kind": "HDD",
        "temp_c": 30,
        **kw,
    }


def _report(*disks):
    return {"smart": list(disks)}


def test_no_smart_data_is_ok_not_an_error():
    # A VM / a host without smartctl sends no "smart" key.
    assert CHECKER.evaluate({}, {})[0] == "ok"


def test_clean_disk_is_ok():
    assert CHECKER.evaluate({}, _report(_disk()))[0] == "ok"


def test_smart_failed_is_critical():
    assert CHECKER.evaluate({}, _report(_disk(smart_passed=False)))[0] == "critical"


def test_offline_uncorrectable_is_critical():
    assert CHECKER.evaluate({}, _report(_disk(uncorrectable=3)))[0] == "critical"


def test_smartctl_prefail_bit_is_critical():
    # 0x10 = prefail attribute below threshold.
    assert CHECKER.evaluate({}, _report(_disk(smartctl_status=0x10)))[0] == "critical"


def test_smartctl_error_log_bit_is_warning():
    # 0x40 = entries in the error log -> warning, not critical.
    assert CHECKER.evaluate({}, _report(_disk(smartctl_status=0x40)))[0] == "warning"


def test_temperature_threshold_depends_on_kind():
    # HDD crit default 60 -> 62 is critical; an SSD at the same 62 (crit 70) is
    # below crit but >= its warn (60) -> warning. Same temperature, different kind.
    assert CHECKER.evaluate({}, _report(_disk(kind="HDD", temp_c=62)))[0] == "critical"
    assert CHECKER.evaluate({}, _report(_disk(kind="SATA-SSD", temp_c=62)))[0] == "warning"


def test_ignored_device_is_skipped():
    cfg = {"ignore_devices": ["/dev/sda"]}
    assert CHECKER.evaluate(cfg, _report(_disk(smart_passed=False)))[0] == "ok"
