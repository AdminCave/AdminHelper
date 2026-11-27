# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SmartHealthChecker.evaluate — disk-health alerting. Focused on the bug-prone
bits: missing SMART data is NOT an error (VMs: info; a failed query or a disk without a
verdict: unknown), a failed/uncorrectable disk is
critical, the smartctl exit-code bit flags map to the right severity, the
temperature threshold depends on the disk kind, and an ignored device is
skipped. (ATA/SATA disks only, to stay clear of the NVMe-spare specifics.)"""

import math
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.check_engine import NOT_COLLECTED, apply_result
from app.checkers import smart
from app.checkers.agent import MAX_REPORT_ENTRIES, NO_RATING
from app.checkers.smart import SmartHealthChecker
from app.exception_scope import mask
from app.models import MonitorCheck, MonitorObjectState, MonitorState
from app.objects import read_objects

from ._helpers import assert_every_reader_reads

CHECKER = SmartHealthChecker()


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    # read_at is the evaluation time: two evaluations compared here read at the same moment.
    monkeypatch.setattr(smart, "_now", lambda: datetime(2026, 11, 19, 4, 0, 0, tzinfo=timezone.utc))


def _disk(**kw):
    # A clean ATA disk by default: passes, no errors, cool.
    return {
        "device": "/dev/sda",
        "model": "X",
        "protocol": "ATA",
        "kind": "HDD",
        "smart_passed": True,
        "temp_c": 30,
        **kw,
    }


def _report(*disks):
    return {"smart": list(disks)}


def test_no_smart_data_is_info_not_an_error():
    # A VM / a host without smartctl sends no "smart" key: not collected (Kevin 2026-11-18).
    assert CHECKER.evaluate({}, {})[0] == "info"


# The result of a report without smart and without a readable reason (agents before R-0419).
_NO_DATA = ("info", "No SMART data (VM or smartctl not available)", None)


@pytest.mark.parametrize(
    ("reason", "status", "message"),
    [
        ("not_installed", "info", "No SMART data: smartctl is not installed"),
        # scan_failed also covers found devices of which none gave readable SMART data:
        # not readable, so unknown, not a healthy ok (R-1568).
        ("scan_failed", "unknown", "No SMART data: the SMART query failed"),
        ("no_devices", "info", "No SMART data: no SMART-capable devices found"),
    ],
)
def test_smart_absent_names_the_reason_and_its_level(reason, status, message):
    # Agents since R-0419 send smart_absent instead of smart when there is no disk.
    report = {"smart_absent": {"reason": reason}}
    assert CHECKER.evaluate({}, report) == (status, message, {"_details": {"absent": reason}})


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


@pytest.mark.parametrize("kind", ["ata", "nvme"])
def test_a_disk_without_a_smart_verdict_is_not_readable_not_failed(kind):
    # R-0518: without smart_status (SMART off) the agent leaves smart_passed out; that is no
    # verdict, so unknown, never "SMART FAILED".
    make_disk = _disk if kind == "ata" else _nvme
    disk = {k: v for k, v in make_disk().items() if k != "smart_passed"}
    status, msg, metrics = CHECKER.evaluate({}, _report(disk))
    label = f"{disk['device']} ({disk['model']})"
    assert (status, msg) == ("unknown", f"SMART not readable: {label}")
    assert _row(metrics)["smart_passed"] is None
    assert _row(metrics)["category"] == "unknown"
    assert metrics["smart_disks_ok"] == 0


def test_an_unreadable_disk_is_named_beside_a_warning_of_another():
    unread = {k: v for k, v in _disk(device="/dev/sdb").items() if k != "smart_passed"}
    status, msg, _ = CHECKER.evaluate({}, _report(_disk(smartctl_status=0x40), unread))
    assert status == "warning"
    assert msg == (
        "SMART warnings: /dev/sda (X): error log entries (smartctl 0x40); "
        "SMART not readable: /dev/sdb (X)"
    )


def test_a_rating_of_its_own_outranks_a_missing_verdict():
    # Temperature and attributes still rate a disk without a verdict: hot is critical.
    disk = {k: v for k, v in _disk(temp_c=62).items() if k != "smart_passed"}
    status, msg, metrics = CHECKER.evaluate({}, _report(disk))
    assert status == "critical"
    assert msg == "SMART problems: /dev/sda (X): 62°C (>=60°C); SMART not readable: /dev/sda (X)"
    assert _row(metrics)["category"] == "critical"


def test_offline_uncorrectable_is_critical():
    assert CHECKER.evaluate({}, _report(_disk(uncorrectable=3)))[0] == "critical"


def test_smartctl_prefail_bit_is_critical():
    # 0x10 = prefail attribute below threshold.
    assert CHECKER.evaluate({}, _report(_disk(smartctl_status=0x10)))[0] == "critical"


def test_smartctl_error_log_bit_is_warning():
    # 0x40 = entries in the error log -> warning, not critical.
    assert CHECKER.evaluate({}, _report(_disk(smartctl_status=0x40)))[0] == "warning"


def test_the_counters_count_disks_not_their_messages():
    # One disk with two critical messages and one with two warnings: two disks, not four.
    failing = _disk(device="/dev/sda", smart_passed=False, temp_c=95)
    warm = _disk(device="/dev/sdb", temp_c=56, smartctl_status=0x40)
    _, _, metrics = CHECKER.evaluate({}, _report(failing, warm))
    assert (metrics["smart_disks_critical"], metrics["smart_disks_warning"]) == (1, 1)


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


def test_an_ignored_disk_is_an_object_marked_with_the_setting():
    sdb = _disk(device="/dev/sdb", model="Y")
    report = _report(_disk(smart_passed=False, wwn="0x5000c500a1b2c3d4"), sdb)
    status, msg, metrics = CHECKER.evaluate({"ignore_devices": ["/dev/sda"]}, report)
    reason = "Excluded by setting ignore_devices"
    sda = _object("0x5000c500a1b2c3d4", "/dev/sda (X)", NOT_COLLECTED, reason)
    assert _objects(metrics) == (
        True,
        [
            {**sda, "excluded": "ignore_devices"},
            _object("/dev/sdb", "/dev/sdb (Y)", "ok", "SMART OK", stable=False),
        ],
    )
    # Check, message and details stay as they are without the disk: it is not rated.
    alone = CHECKER.evaluate({}, _report(sdb))
    assert (status, msg, metrics["_details"]) == (alone[0], alone[1], alone[2]["_details"])


def test_an_ignored_disk_asleep_is_no_object():
    # Asleep the agent sends the device path alone (smart.go): no key to name the disk by.
    asleep = {"device": "/dev/sda", "standby": True}
    report = _report(asleep, _disk(device="/dev/sdb"))
    _, _, metrics = CHECKER.evaluate({"ignore_devices": ["/dev/sda"]}, report)
    complete, items = _objects(metrics)
    # Incomplete (R-1793): the excluded object it named awake must not turn gone.
    assert (complete, [item["id"] for item in items]) == (False, ["/dev/sdb"])
    # Paired: not ignored, the sleeping disk is an object under its path.
    _, _, metrics = CHECKER.evaluate({}, report)
    assert [item["id"] for item in _objects(metrics)[1]] == ["/dev/sda", "/dev/sdb"]


def test_an_ignored_disk_falling_asleep_keeps_its_object(db_engine):
    """R-1793: awake the excluded disk is an object; asleep it sends no key to name it by, and
    the next result must not mark the object gone, or it flickers with every standby."""
    factory = sessionmaker(bind=db_engine)
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                server_id="srv-1",
                name="disks",
                check_type="smart_health",
                config="{}",
                enabled=True,
                consecutive_fails=1,
                consecutive_oks=1,
            )
        )
        db.commit()
    cfg = {"ignore_devices": ["/dev/sda"]}
    sdb = _disk(device="/dev/sdb", model="Y")
    awake = _disk(wwn="0x5000c500a1b2c3d4")
    asleep = {"device": "/dev/sda", "standby": True}
    start = datetime(2026, 11, 19, 4, 0, 0)
    for minute, sda in enumerate((awake, asleep)):
        status, message, metrics = CHECKER.evaluate(cfg, _report(sda, sdb))
        with factory() as db:
            check = db.get(MonitorCheck, "c1")
            state = db.query(MonitorState).filter_by(check_id="c1").first()
            at = start + timedelta(minutes=minute)
            apply_result(
                db, check, state, status, message, metrics, at, objects=metrics["_objects"]
            )
            db.commit()
    with factory() as db:
        gone = {row.name: row.gone_at for row in db.query(MonitorObjectState).all()}
    assert gone == {"/dev/sda (X)": None, "/dev/sdb (Y)": None}


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
        "smart_passed": True,
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
    status, msg, metrics = CHECKER.evaluate(cfg, _report(disk))
    objects = metrics.pop("_objects")
    assert (status, msg, metrics) == (
        "ok",
        "All 0 disks SMART OK",
        {
            "smart_disks_ok": 0,
            "smart_disks_warning": 0,
            "smart_disks_critical": 0,
            "_details": {"disks": []},
        },
    )
    # The ignored disk is named excluded under its capped path, and the result is complete.
    reason = "Excluded by setting ignore_devices"
    excluded = _object(_LONG_SHOWN, f"{_LONG_SHOWN} (X)", NOT_COLLECTED, reason, stable=False)
    assert objects == {"complete": True, "items": [{**excluded, "excluded": "ignore_devices"}]}


@pytest.mark.parametrize(
    ("value", "passed"),
    [
        pytest.param(True, True, id="true"),
        pytest.param(False, False, id="false"),
        pytest.param(None, None, id="null"),
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
    # A false value is "SMART FAILED", a true one rates like a passed disk, null like no verdict.
    result = _rate_with(make_disk(), "smart_passed", value)
    if passed:
        assert result == CHECKER.evaluate({}, _report(make_disk()))
    elif passed is None:
        assert result[0] == "unknown" and result[1].startswith("SMART not readable: ")
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


# R-1569: a disk the agent left asleep (smartctl -n standby,3) keeps its last read state.


def _asleep(device="/dev/sda"):
    return {"device": device, "standby": True}


def test_a_read_disk_carries_the_time_it_was_read():
    _, _, metrics = CHECKER.evaluate({}, _report(_disk()))
    disk = metrics["_details"]["disks"][0]
    assert disk["read_at"] == "2026-11-19T04:00:00Z"
    assert "standby" not in disk


def test_a_sleeping_disk_keeps_its_last_state_and_its_problems():
    _, _, first = CHECKER.evaluate(
        {}, _report(_disk(reallocated_sectors=3), _disk(device="/dev/sdb"))
    )
    prev = first["_details"]
    status, message, metrics = CHECKER.evaluate(
        {}, _report(_asleep(), _disk(device="/dev/sdb")), prev
    )
    sda = metrics["_details"]["disks"][0]
    assert status == "warning"
    assert message == "SMART warnings: /dev/sda (X): warning when last read (asleep), 1 asleep"
    assert sda == {**prev["disks"][0], "standby": True}
    assert sda["reallocated_sectors"] == 3 and sda["read_at"] == prev["disks"][0]["read_at"]
    # No values came: no series for the sleeping disk, the read one has its own.
    assert not any(k.endswith("dev_sda") for k in metrics if k.startswith("smart_"))
    assert "smart_reallocated_dev_sdb" in metrics


def test_a_sleeping_disk_without_a_last_state_is_ok_not_unreadable():
    status, message, metrics = CHECKER.evaluate({}, _report(_asleep(), _disk(device="/dev/sdb")))
    assert (status, message) == ("ok", "All 2 disks SMART OK, 1 asleep")
    assert metrics["_details"]["disks"][0] == {
        "device": "/dev/sda",
        "category": "ok",
        "standby": True,
    }


def test_a_disk_asleep_twice_keeps_the_first_read(monkeypatch):
    _, _, first = CHECKER.evaluate({}, _report(_disk(smart_passed=False)))
    monkeypatch.setattr(smart, "_now", lambda: datetime(2026, 11, 19, 5, 0, 0, tzinfo=timezone.utc))
    _, _, second = CHECKER.evaluate({}, _report(_asleep()), first["_details"])
    status, _, third = CHECKER.evaluate({}, _report(_asleep()), second["_details"])
    assert status == "critical"
    assert third["_details"]["disks"][0]["read_at"] == "2026-11-19T04:00:00Z"


@pytest.mark.parametrize(
    "prev",
    [
        None,
        {},
        {"disks": "x"},
        {"disks": [1, {"device": 2}]},
        {"disks": [{"device": "/dev/sda", "category": "bad"}]},
    ],
)
def test_a_broken_last_state_leaves_the_sleeping_disk_ok(prev):
    status, _, metrics = CHECKER.evaluate({}, _report(_asleep()), prev)
    assert status == "ok"
    assert metrics["_details"]["disks"][0]["category"] == "ok"


def test_standby_must_be_true_not_truthy():
    # Only the agent's boolean marks a disk asleep; anything else is graded as sent.
    status, _, _ = CHECKER.evaluate({}, _report(_disk(standby="yes", smart_passed=False)))
    assert status == "critical"


def test_a_disk_last_read_without_a_verdict_stays_not_readable_asleep():
    # Sleeping changes nothing about the last state: no flapping between unknown and ok.
    _, read_msg, first = CHECKER.evaluate(
        {}, _report(_disk(smart_passed=None), _disk(device="/dev/sdb"))
    )
    status, message, _ = CHECKER.evaluate(
        {}, _report(_asleep(), _disk(device="/dev/sdb")), first["_details"]
    )
    assert status == "unknown"
    assert message == read_msg + ", 1 asleep"


# R-1559: each disk is an object of its own, as GET /objects shows it.


def _objects(metrics: dict) -> tuple[bool, list[dict]]:
    """complete and the items of the object block; app.objects must take each item."""
    block = metrics["_objects"]
    assert len(read_objects(block, "srv-1")[1]) == len(block["items"]), block
    return block["complete"], block["items"]


def _object(ident, name, status, reason, stable=True):
    return {
        "kind": "disk",
        "id": ident,
        "name": name,
        "status": status,
        "reason": reason,
        "stable": stable,
    }


def test_each_read_disk_is_an_object_with_its_first_problem():
    _, _, metrics = CHECKER.evaluate(
        {},
        _report(
            _disk(serial="S1"),
            _disk(device="/dev/sdb", serial="S2", reallocated_sectors=3, pending_sectors=1),
            _disk(device="/dev/sdc", serial="S3", smart_passed=None),
            _disk(device="/dev/sdd", serial="S4", smart_passed=False, temp_c=58),
        ),
    )
    assert _objects(metrics) == (
        True,
        [
            _object("X/S1", "/dev/sda (X)", "ok", "SMART OK"),
            _object("X/S2", "/dev/sdb (X)", "warning", "3 reallocated sectors"),
            _object("X/S3", "/dev/sdc (X)", "unknown", "SMART not readable"),
            # A critical problem comes before a warning.
            _object("X/S4", "/dev/sdd (X)", "critical", "SMART FAILED"),
        ],
    )


def test_a_disk_is_keyed_by_its_wwn_else_model_and_serial_else_its_device():
    _, _, metrics = CHECKER.evaluate(
        {},
        _report(
            _disk(serial="S1", wwn="5000c500a1b2c3d4"),
            _disk(device="/dev/sdb", serial="S2"),
            _disk(device="/dev/sdc"),
            _disk(device="/dev/sdd", model=None, serial="S4"),
        ),
    )
    _, items = _objects(metrics)
    assert [(item["id"], item["stable"]) for item in items] == [
        ("5000c500a1b2c3d4", True),
        ("X/S2", True),
        # The device path may change on a reboot.
        ("/dev/sdc", False),
        ("/dev/sdd", False),
    ]
    assert items[3]["name"] == "/dev/sdd (?)"


def test_a_sleeping_disk_read_before_keeps_its_object_and_the_result_is_incomplete():
    _, _, first = CHECKER.evaluate(
        {}, _report(_disk(serial="S1"), _disk(device="/dev/sdb", serial="S2"))
    )
    assert _objects(first)[0] is True

    _, _, metrics = CHECKER.evaluate(
        {}, _report(_asleep(), _disk(device="/dev/sdb", serial="S2")), first["_details"]
    )
    complete, items = _objects(metrics)
    # Asleep it sent no serial: no item, and its object must not be marked gone.
    assert (complete, [item["id"] for item in items]) == (False, ["X/S2"])


def test_a_disk_asleep_since_it_was_first_seen_is_not_collected():
    report = _report(_asleep(), _disk(device="/dev/sdb", serial="S2"))
    _, _, metrics = CHECKER.evaluate({}, report)
    complete, items = _objects(metrics)
    assert complete is True
    assert items[0] == _object(
        "/dev/sda", "/dev/sda", NOT_COLLECTED, "Asleep, not read yet", stable=False
    )

    # Asleep on the next report too: its last state was never read.
    _, _, again = CHECKER.evaluate({}, report, metrics["_details"])
    assert _objects(again) == (True, items)


def test_a_disk_list_cut_at_the_report_limit_is_incomplete():
    disks = [_disk(device=f"/dev/sd{i}", serial=f"S{i}") for i in range(MAX_REPORT_ENTRIES + 1)]
    complete, items = _objects(CHECKER.evaluate({}, _report(*disks))[2])
    assert (complete, len(items)) == (False, MAX_REPORT_ENTRIES)
    # Paired: at the limit the list is whole.
    complete, items = _objects(CHECKER.evaluate({}, _report(*disks[:-1]))[2])
    assert (complete, len(items)) == (True, MAX_REPORT_ENTRIES)


def test_a_disk_entry_that_is_no_object_makes_the_result_incomplete():
    # The checker skips it, and the disk it stood for must not be marked gone.
    complete, items = _objects(CHECKER.evaluate({}, _report(_disk(), "sdb"))[2])
    assert (complete, len(items)) == (False, 1)


# A device name of the agent (docs/developer/agent.html, smartDiskID) whose bracket fnmatch
# reads as a class, and the name that class would match (R-1637).
_MEGARAID = "/dev/bus/0 [megaraid_disk_00]"
_CLASS_MATCH = "/dev/bus/0 m"


def _marks(metrics: dict) -> list[tuple[str, str, str | None]]:
    return [(i["id"], i["status"], i.get("excluded")) for i in _objects(metrics)[1]]


def test_ignore_devices_excludes_a_device_name_with_brackets_itself_and_nothing_else():
    report = _report(
        _disk(device=_MEGARAID, smart_passed=False), _disk(device=_CLASS_MATCH, smart_passed=False)
    )
    status, _, metrics = CHECKER.evaluate({"ignore_devices": [_MEGARAID]}, report)
    assert status == "critical"
    assert _marks(metrics) == [
        (_MEGARAID, NOT_COLLECTED, "ignore_devices"),
        (_CLASS_MATCH, "critical", None),
    ]
    # No series for the excluded device, as before.
    assert f"smart_reallocated_{smart.safe_metric_part(_MEGARAID)}" not in metrics
    assert f"smart_reallocated_{smart.safe_metric_part(_CLASS_MATCH)}" in metrics


def test_a_no_rating_exception_excludes_the_disks_its_pattern_matches_under_its_id():
    devices = (_MEGARAID, _CLASS_MATCH, "/dev/sdb", "/dev/sdc")
    report = _report(*(_disk(device=d, smart_passed=False) for d in devices))
    config = {NO_RATING: [(mask(_MEGARAID), "exc-1"), ("/dev/sd*", "exc-2")]}
    status, _, metrics = CHECKER.evaluate(config, report)
    assert status == "critical"
    assert _marks(metrics) == [
        (_MEGARAID, NOT_COLLECTED, "exc-1"),
        (_CLASS_MATCH, "critical", None),
        ("/dev/sdb", NOT_COLLECTED, "exc-2"),
        ("/dev/sdc", NOT_COLLECTED, "exc-2"),
    ]
    reasons = {i["reason"] for i in _objects(metrics)[1] if i.get("excluded")}
    assert reasons == {"Excluded by exception"}
    assert [m for m in metrics if m.startswith("smart_reallocated_")] == [
        f"smart_reallocated_{smart.safe_metric_part(_CLASS_MATCH)}"
    ]


def test_a_disk_the_setting_and_an_exception_both_exclude_names_the_setting():
    report = _report(_disk(device="/dev/sdb"), _disk(device="/dev/sdc"))
    config = {"ignore_devices": ["/dev/sdb"], NO_RATING: [("/dev/sd*", "exc-1")]}
    _, _, metrics = CHECKER.evaluate(config, report)
    assert _marks(metrics) == [
        ("/dev/sdb", NOT_COLLECTED, "ignore_devices"),
        ("/dev/sdc", NOT_COLLECTED, "exc-1"),
    ]


def test_a_disk_an_exception_excludes_asleep_is_no_object_and_the_result_incomplete():
    # As with the setting (R-1793): the object it named awake must not turn gone.
    report = _report(_asleep("/dev/sda"), _disk(device="/dev/nvme0"))
    _, _, metrics = CHECKER.evaluate({NO_RATING: [("/dev/sd*", "exc-1")]}, report)
    complete, items = _objects(metrics)
    assert (complete, [item["id"] for item in items]) == (False, ["/dev/nvme0"])
