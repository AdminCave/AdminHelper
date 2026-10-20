# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SmartHealthChecker.evaluate — disk-health alerting. Focused on the bug-prone
bits: missing SMART data is NOT an error (VMs), a failed/uncorrectable disk is
critical, the smartctl exit-code bit flags map to the right severity, the
temperature threshold depends on the disk kind, and an ignored device is
skipped. (ATA/SATA disks only, to stay clear of the NVMe-spare specifics.)"""

import math

import pytest

from app.checkers.smart import SmartHealthChecker

from ._helpers import assert_every_reader_reads

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


# The result of a report without smart and without a readable reason (agents before R-0419).
_NO_DATA = ("ok", "No SMART data (VM or smartctl not available)", None)


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("not_installed", "No SMART data: smartctl is not installed"),
        # scan_failed also covers found devices of which none gave readable SMART data.
        ("scan_failed", "No SMART data: the SMART query failed"),
        ("no_devices", "No SMART data: no SMART-capable devices found"),
    ],
)
def test_smart_absent_names_the_reason_and_stays_ok(reason, message):
    # Agents since R-0419 send smart_absent instead of smart when there is no disk.
    report = {"smart_absent": {"reason": reason}}
    assert CHECKER.evaluate({}, report) == ("ok", message, {"_details": {"absent": reason}})


@pytest.mark.parametrize(
    "absent",
    [
        {"reason": "vm_detected"},
        {"reason": ["not_installed"]},
        {},
        "not_installed",
        ["not_installed"],
        None,
    ],
)
def test_smart_absent_unknown_or_malformed_falls_back_to_no_data(absent):
    assert CHECKER.evaluate({}, {"smart_absent": absent}) == _NO_DATA


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


def test_disk_list_is_capped():
    # Like the plugin lists, only the first 500 disks are rated, so a broken agent cannot
    # flood the details, the message and the per-disk metrics (R-0486).
    devices = [f"/dev/sd{i}" for i in range(2000)]
    status, msg, metrics = CHECKER.evaluate({}, _report(*(_disk(device=d) for d in devices)))
    assert (status, msg) == ("ok", "All 500 disks SMART OK")
    assert [d["device"] for d in metrics["_details"]["disks"]] == devices[:500]
    assert sum(k.startswith("smart_temp_") for k in metrics) == 500


@pytest.mark.parametrize("smart", ["abc", {"device": "/dev/sda"}, 42], ids=["str", "dict", "int"])
def test_smart_that_is_no_list_counts_as_no_data(smart):
    assert CHECKER.evaluate({}, {"smart": smart}) == _NO_DATA


def test_disk_that_is_no_object_is_skipped():
    status, msg, metrics = CHECKER.evaluate({}, _report("x", _disk(smart_passed=False)))
    assert (status, msg) == ("critical", "SMART problems: /dev/sda (X): SMART FAILED")
    assert [d["device"] for d in metrics["_details"]["disks"]] == ["/dev/sda"]


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


# --- Fields of the wrong JSON type in a disk entry (R-0517) ---
# What a broken or hijacked agent can put where a number or a text belongs. A regular agent sends
# SmartDisk (apps/agent/internal/monitor/smart.go) with Go ints and strings; before R-0517 most of
# these raised in evaluate (the push path then leaves the check's state as it was) or went raw into
# message, metrics and _details. A field of the wrong type counts as missing: the result equals
# the one without the field.
_BIG_INT = 10**400  # beyond float range: math.isfinite raises OverflowError on it
_NOT_NUMBERS = [
    pytest.param("12", id="numeric-str"),
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
# Every int field of SmartDisk in apps/agent/internal/monitor/smart.go.
_NUMBER_FIELDS = [
    "temp_c",
    "power_on_hours",
    "smartctl_status",
    "reallocated_sectors",
    "spin_retry_count",
    "reallocation_events",
    "pending_sectors",
    "uncorrectable",
    "reported_uncorrect",
    "udma_crc_errors",
    "available_spare_pct",
    "percentage_used",
    "media_errors",
    "critical_warning",
]
# ATA attributes an NVMe disk neither rates nor lists in _details.
_ATA_ONLY = ("spin_retry_count", "reallocation_events")
_DISKS = [pytest.param(_disk, id="ata"), pytest.param(_nvme, id="nvme")]


def _without(disk, field):
    return {key: value for key, value in disk.items() if key != field}


def _rate_with(disk, field, value):
    return CHECKER.evaluate({}, _report({**disk, field: value}))


@pytest.mark.parametrize("value", _NOT_NUMBERS)
@pytest.mark.parametrize("field", _NUMBER_FIELDS)
@pytest.mark.parametrize("make_disk", _DISKS)
def test_a_number_field_that_is_no_json_number_counts_as_missing(make_disk, field, value):
    disk = _without(make_disk(), field)
    assert _rate_with(disk, field, value) == CHECKER.evaluate({}, _report(disk))


@pytest.mark.parametrize(
    ("make_disk", "field"),
    [pytest.param(_disk, f, id=f"ata-{f}") for f in _NUMBER_FIELDS]
    + [pytest.param(_nvme, f, id=f"nvme-{f}") for f in _NUMBER_FIELDS if f not in _ATA_ONLY],
)
def test_a_json_number_in_such_a_field_is_read(make_disk, field):
    # The counterpart of the cases above: the field is read, a JSON number changes the result.
    disk = _without(make_disk(), field)
    assert _rate_with(disk, field, 12) != CHECKER.evaluate({}, _report(disk))


_NOT_TEXTS = [
    pytest.param([1], id="list"),
    pytest.param({"a": 1}, id="dict"),
    pytest.param(5, id="int"),
    pytest.param(None, id="null"),
]


@pytest.mark.parametrize("value", _NOT_TEXTS)
@pytest.mark.parametrize("field", ["device", "kind"])
@pytest.mark.parametrize("make_disk", _DISKS)
def test_device_or_kind_that_is_no_string_counts_as_missing(make_disk, field, value):
    disk = _without(make_disk(), field)
    assert _rate_with(disk, field, value) == CHECKER.evaluate({}, _report(disk))


def test_device_that_is_no_string_is_named_question_mark():
    disk = _disk(device=["/dev/sda"], smart_passed=False)
    status, msg, metrics = CHECKER.evaluate({}, _report(disk))
    assert (status, msg) == ("critical", "SMART problems: ? (X): SMART FAILED")
    assert metrics["_details"]["disks"][0]["device"] == "?"
    assert metrics["smart_reallocated_unknown"] == 0  # safe_metric_part("?")


def test_kind_that_is_no_string_follows_the_protocol():
    # 70 °C is a warning by the NVMe thresholds (65/75), critical by the HDD ones (55/60).
    status, msg, metrics = CHECKER.evaluate({}, _report(_nvme(kind=["HDD"], temp_c=70)))
    assert (status, msg) == ("warning", "SMART warnings: /dev/nvme0 (N): 70°C (>=65°C)")
    assert metrics["_details"]["disks"][0]["kind"] == "NVMe"


# --- Text fields and smart_passed in _details ---
# _details goes as it is into the answers of GET /status and GET /checks, which the desktop reads
# as a whole: a 400-digit integer there is no number every JSON reader takes. device, model, kind
# and protocol go into _details (device and model also into the label of the message) only as a
# string, on one line and cut to 500 characters by cap_agent_text; anything else counts as
# missing, with the default. smart_passed goes into _details as the bool the rating reads.
_LONG_TEXT = "line\n" * 2000  # 10 000 characters
_LONG_SHOWN = ("line " * 2000)[:499] + "\u2026"
_NOT_STRINGS = [
    pytest.param(_BIG_INT, id="int-400-digits"),
    pytest.param([1], id="list"),
    pytest.param({"a": 1}, id="dict"),
]
# (disk, field, the field's value in _details without it)
_TEXT_FIELDS = [
    pytest.param(make_disk, field, default, id=f"{name}-{field}")
    for name, make_disk, kind in (("ata", _disk, "HDD"), ("nvme", _nvme, "NVMe"))
    for field, default in (("device", "?"), ("model", "?"), ("kind", kind), ("protocol", "ATA"))
]


def _row(metrics):
    [row] = metrics["_details"]["disks"]
    return row


@pytest.mark.parametrize("value", _NOT_STRINGS)
@pytest.mark.parametrize(("make_disk", "field", "default"), _TEXT_FIELDS)
def test_a_text_field_that_is_no_string_shows_the_default_in_details(
    make_disk, field, default, value
):
    disk = _without(make_disk(), field)
    result = _rate_with(disk, field, value)
    assert result == CHECKER.evaluate({}, _report(disk))
    assert _row(result[2])[field] == default
    assert_every_reader_reads(result[2]["_details"])


@pytest.mark.parametrize("field", ["device", "model", "kind", "protocol"])
@pytest.mark.parametrize("make_disk", _DISKS)
def test_a_long_text_field_goes_into_details_on_one_line_of_500_characters(make_disk, field):
    status, msg, metrics = _rate_with(make_disk(), field, _LONG_TEXT)
    assert _row(metrics)[field] == _LONG_SHOWN
    assert status == CHECKER.evaluate({}, _report(make_disk()))[0]
    assert msg.isprintable()  # no control character, no line or paragraph separator
    assert_every_reader_reads(metrics["_details"])


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("device", "SMART problems: " + _LONG_SHOWN),
        ("model", "SMART problems: " + ("/dev/sda (" + "line " * 2000)[:499] + "\u2026"),
    ],
)
def test_a_long_device_or_model_goes_into_the_message_on_one_line(field, message):
    assert _rate_with(_disk(smart_passed=False), field, _LONG_TEXT)[:2] == ("critical", message)


def test_the_ignore_list_compares_the_full_device():
    cfg = {"ignore_devices": [_LONG_TEXT]}
    disk = _disk(device=_LONG_TEXT, smart_passed=False)
    assert CHECKER.evaluate(cfg, _report(disk)) == (
        "ok",
        "All 0 disks SMART OK",
        {
            "smart_disks_ok": 0,
            "smart_disks_warning": 0,
            "smart_disks_critical": 0,
            "_details": {"disks": []},
        },
    )


@pytest.mark.parametrize(
    ("value", "passed"),
    [
        pytest.param(True, True, id="true"),
        pytest.param(False, False, id="false"),
        pytest.param(None, False, id="null"),
        pytest.param(0, False, id="zero"),
        pytest.param("", False, id="empty-str"),
        pytest.param([], False, id="empty-list"),
        pytest.param({}, False, id="empty-dict"),
        pytest.param(_BIG_INT, True, id="int-400-digits"),
        pytest.param([1], True, id="list"),
        pytest.param({"a": 1}, True, id="dict"),
    ],
)
@pytest.mark.parametrize("make_disk", _DISKS)
def test_smart_passed_in_details_is_the_bool_the_rating_reads(make_disk, value, passed):
    # The rating stays: a false value is "SMART FAILED", a true one rates like a missing field.
    result = _rate_with(make_disk(), "smart_passed", value)
    if passed:
        assert result == CHECKER.evaluate({}, _report(make_disk()))
    else:
        assert result[0] == "critical" and result[1].endswith(": SMART FAILED")
    assert _row(result[2])["smart_passed"] is passed
    assert_every_reader_reads(result[2]["_details"])


def test_text_fields_of_a_regular_report():
    status, msg, metrics = CHECKER.evaluate({}, _report(_disk(), _nvme(smart_passed=False)))
    assert (status, msg) == ("critical", "SMART problems: /dev/nvme0 (N): SMART FAILED")
    shown = [
        {key: disk[key] for key in ("device", "model", "protocol", "kind", "smart_passed")}
        for disk in metrics["_details"]["disks"]
    ]
    assert shown == [
        {
            "device": "/dev/sda",
            "model": "X",
            "protocol": "ATA",
            "kind": "HDD",
            "smart_passed": True,
        },
        {
            "device": "/dev/nvme0",
            "model": "N",
            "protocol": "NVMe",
            "kind": "NVMe",
            "smart_passed": False,
        },
    ]
    assert_every_reader_reads(metrics["_details"])
