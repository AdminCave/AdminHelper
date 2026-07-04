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


def test_running_critical_is_not_downgraded_by_a_protocol_warning():
    # 2.32: evaluate merges the per-disk category across the universal/temp checks
    # and the protocol-specific one. A prefail-critical disk (smartctl 0x10) that
    # also trips only an ATA warning (reallocated >= warn 1, < crit 10) must STAY
    # critical — the protocol check now returns a local "warning" that the merge
    # must not let downgrade the running critical.
    disk = _disk(smartctl_status=0x10, reallocated_sectors=1)
    assert CHECKER.evaluate({}, _report(disk))[0] == "critical"


def test_protocol_critical_escalates_a_running_warning():
    # The reverse: a temperature warning (SSD at 62, warn 60) plus an ATA critical
    # (spin_retry) must escalate the disk to critical.
    disk = _disk(kind="SATA-SSD", temp_c=62, spin_retry_count=1)
    assert CHECKER.evaluate({}, _report(disk))[0] == "critical"


def test_ignored_device_is_skipped():
    cfg = {"ignore_devices": ["/dev/sda"]}
    assert CHECKER.evaluate(cfg, _report(_disk(smart_passed=False)))[0] == "ok"


def _nvme(**kw):
    # A clean NVMe disk by default (cool, full spare implied by the defaults).
    return {
        "device": "/dev/nvme0",
        "model": "N",
        "protocol": "NVMe",
        "kind": "NVMe",
        "temp_c": 40,
        **kw,
    }


# NVMe available_spare is INVERTED: a value BELOW the threshold is the problem
# (a worn drive runs out of spare blocks). Defaults: warn <20%, crit <10%.
def test_nvme_available_spare_below_crit_is_critical():
    assert CHECKER.evaluate({}, _report(_nvme(available_spare_pct=5)))[0] == "critical"


def test_nvme_available_spare_below_warn_is_warning():
    assert CHECKER.evaluate({}, _report(_nvme(available_spare_pct=15)))[0] == "warning"


def test_nvme_full_spare_is_ok():
    assert CHECKER.evaluate({}, _report(_nvme(available_spare_pct=100)))[0] == "ok"


# percentage_used is the normal direction (>= threshold is bad): warn 90, crit 100.
def test_nvme_percentage_used_at_crit_is_critical():
    assert CHECKER.evaluate({}, _report(_nvme(percentage_used=100)))[0] == "critical"


def test_nvme_percentage_used_at_warn_is_warning():
    assert CHECKER.evaluate({}, _report(_nvme(percentage_used=95)))[0] == "warning"


def test_nvme_media_errors_is_critical():
    assert CHECKER.evaluate({}, _report(_nvme(media_errors=2)))[0] == "critical"


# ATA wear attributes.
def test_ata_reallocated_sectors_thresholds():
    assert (
        CHECKER.evaluate({}, _report(_disk(reallocated_sectors=10)))[0] == "critical"
    )  # >= crit 10
    assert CHECKER.evaluate({}, _report(_disk(reallocated_sectors=1)))[0] == "warning"  # >= warn 1


def test_ata_pending_sectors_at_crit_is_critical():
    assert CHECKER.evaluate({}, _report(_disk(pending_sectors=5)))[0] == "critical"


def test_ata_spin_retry_is_critical():
    assert CHECKER.evaluate({}, _report(_disk(spin_retry_count=1)))[0] == "critical"
