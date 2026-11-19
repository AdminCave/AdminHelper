# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""system_state (R-0423): the four points of the agent's system_state block, each at most a
warning, each switchable; the clock only after 15 min of uptime; anything but a JSON bool or a
whole JSON number counts as missing; a report without the block is not evaluated."""

import json

import pytest

from app.check_engine import NOT_COLLECTED
from app.check_types import PUSH_ONLY_TYPES
from app.checkers import get_checker
from app.checkers.system import SystemStateChecker
from app.models import MonitorCheck, MonitorObjectState, MonitorState
from app.objects import read_objects

from ._helpers import assert_every_reader_reads

_HEALTHY = {
    "reboot_required": False,
    "time_synchronized": True,
    "security_updates": 0,
    "oom_kills": 0,
}

_NOTHING = {
    "reboot_required": None,
    "time_synchronized": None,
    "security_updates": None,
    "oom_kills": None,
    "problems": [],
}

# Not evaluated: what the objects stood for is not gone (R-1559).
_UNREAD = {"complete": False, "items": []}


def _object(kind, name, status, reason):
    return {"kind": kind, "id": None, "name": name, "status": status, "reason": reason}


_REBOOT_OK = _object("reboot", "Reboot", "ok", "No reboot required")
_UPDATES_OK = _object("updates", "Security updates", "ok", "No security updates pending")
_CLOCK_OK = _object("clock", "Clock", "ok", "Synchronized")


def _object_result(metrics: dict) -> tuple[bool, list[dict]]:
    """complete and the items of the object block; app.objects must take each item."""
    block = metrics["_objects"]
    assert len(read_objects(block, "srv-1")[1]) == len(block["items"]), block
    return block["complete"], block["items"]


def _rate(config=None, uptime=3600, **fields):
    report = {"system_state": {**_HEALTHY, **fields}}
    if uptime is not None:
        report["uptime_seconds"] = uptime
    return SystemStateChecker().evaluate(config or {}, report)


def test_run_waits_for_agent_data():
    assert SystemStateChecker().run({}) == ("unknown", "Waiting for agent data", None)


def test_registered_as_push_type():
    assert "system_state" in PUSH_ONLY_TYPES
    assert isinstance(get_checker("system_state"), SystemStateChecker)


def test_healthy_state_is_ok_with_the_values_in_details():
    status, msg, metrics = _rate()
    assert (status, msg) == ("ok", "System state OK")
    assert metrics == {
        "_details": {**_HEALTHY, "problems": []},
        "_objects": {"complete": True, "items": [_REBOOT_OK, _UPDATES_OK, _CLOCK_OK]},
    }


@pytest.mark.parametrize(
    ("fields", "message", "problem", "objects"),
    [
        pytest.param(
            {"reboot_required": True},
            "Reboot required",
            "reboot",
            [_object("reboot", "Reboot", "warning", "Reboot required"), _UPDATES_OK, _CLOCK_OK],
            id="reboot",
        ),
        pytest.param(
            {"time_synchronized": False},
            "Clock not synchronized",
            "time_sync",
            [
                _REBOOT_OK,
                _UPDATES_OK,
                _object("clock", "Clock", "warning", "Clock not synchronized"),
            ],
            id="time-sync",
        ),
        pytest.param(
            {"security_updates": 3},
            "3 security updates pending",
            "security_updates",
            [
                _REBOOT_OK,
                _object("updates", "Security updates", "warning", "3 security updates pending"),
                _CLOCK_OK,
            ],
            id="security-updates",
        ),
        # An OOM kill is an event, no object: the objects stay ok.
        pytest.param(
            {"oom_kills": 2},
            "2 OOM kills since last report",
            "oom",
            [_REBOOT_OK, _UPDATES_OK, _CLOCK_OK],
            id="oom",
        ),
    ],
)
def test_each_point_alone_is_a_warning(fields, message, problem, objects):
    status, msg, metrics = _rate(**fields)
    assert (status, msg) == ("warning", message)
    assert metrics == {
        "_details": {**_HEALTHY, **fields, "problems": [problem]},
        "_objects": {"complete": True, "items": objects},
    }
    assert _object_result(metrics) == (True, objects)


def test_all_points_together_in_one_message():
    status, msg, metrics = _rate(
        reboot_required=True, time_synchronized=False, security_updates=3, oom_kills=2
    )
    assert status == "warning"
    assert msg == (
        "Reboot required; Clock not synchronized; 3 security updates pending; "
        "2 OOM kills since last report"
    )
    assert metrics["_details"]["problems"] == ["reboot", "time_sync", "security_updates", "oom"]


_ALL_BAD = {
    "reboot_required": True,
    "time_synchronized": False,
    "security_updates": 3,
    "oom_kills": 2,
}


@pytest.mark.parametrize(
    ("switch", "problem"),
    [
        ("check_reboot", "reboot"),
        ("check_time_sync", "time_sync"),
        ("check_security_updates", "security_updates"),
        ("check_oom", "oom"),
    ],
)
def test_a_switched_off_point_is_no_problem_but_stays_in_details(switch, problem):
    status, _, metrics = _rate({switch: False}, **_ALL_BAD)
    assert status == "warning"
    details = metrics["_details"]
    assert problem not in details["problems"]
    assert len(details["problems"]) == 3
    assert {k: details[k] for k in _ALL_BAD} == _ALL_BAD


def test_every_point_switched_off_is_ok():
    off = {k: False for k in ("check_reboot", "check_time_sync", "check_security_updates")}
    status, msg, metrics = _rate({**off, "check_oom": False}, **_ALL_BAD)
    assert (status, msg) == ("ok", "System state OK")
    assert metrics["_details"] == {**_ALL_BAD, "problems": []}


@pytest.mark.parametrize("value", ["false", 0, None, [], "off"])
def test_only_a_real_false_switches_a_point_off(value):
    status, msg, _ = _rate({"check_reboot": value}, reboot_required=True)
    assert (status, msg) == ("warning", "Reboot required")


@pytest.mark.parametrize(
    ("uptime", "status"),
    [
        pytest.param(600, "ok", id="600s-grace"),
        pytest.param(899, "ok", id="899s-grace"),
        pytest.param(900, "warning", id="900s"),
        pytest.param(86400, "warning", id="a-day"),
        pytest.param(None, "warning", id="missing"),
        pytest.param("1200", "warning", id="string-counts-as-missing"),
        pytest.param(True, "warning", id="bool-counts-as-missing"),
    ],
)
def test_clock_is_rated_from_15_minutes_of_uptime(uptime, status):
    got, _, metrics = _rate(uptime=uptime, time_synchronized=False)
    assert got == status
    # Within the grace period the value still shows; only the rating waits.
    assert metrics["_details"]["time_synchronized"] is False


def test_grace_period_holds_back_only_the_clock():
    status, msg, metrics = _rate(uptime=600, time_synchronized=False, oom_kills=1)
    assert (status, msg) == ("warning", "1 OOM kills since last report")
    assert metrics["_details"]["problems"] == ["oom"]


@pytest.mark.parametrize("field", ["reboot_required", "time_synchronized"])
@pytest.mark.parametrize("value", ["true", "false", 1, 0, 2.5, None, {}, []])
def test_a_flag_that_is_no_json_bool_counts_as_missing(field, value):
    status, msg, metrics = _rate(**{field: value})
    assert (status, msg) == ("ok", "System state OK")
    assert metrics["_details"][field] is None


@pytest.mark.parametrize("field", ["security_updates", "oom_kills"])
@pytest.mark.parametrize(
    "value", [True, False, "3", 2.5, 3.0, float("inf"), float("nan"), 10**400, None, []]
)
def test_a_count_that_is_no_whole_json_number_counts_as_missing(field, value):
    status, msg, metrics = _rate(**{field: value})
    assert (status, msg) == ("ok", "System state OK")
    assert metrics["_details"][field] is None
    assert_every_reader_reads(metrics["_details"])


@pytest.mark.parametrize("field", ["security_updates", "oom_kills"])
@pytest.mark.parametrize(("count", "status"), [(0, "ok"), (1, "warning")])
def test_a_count_from_one_is_a_problem(field, count, status):
    got, _, metrics = _rate(**{field: count})
    assert got == status
    assert metrics["_details"][field] == count


def test_a_large_count_goes_into_details_readable():
    status, msg, metrics = _rate(security_updates=10**300)
    assert status == "warning"
    assert msg == f"{10**300} security updates pending"
    assert_every_reader_reads(metrics["_details"])


def test_a_partial_block_rates_what_is_there():
    # The agent sends a field only when it could determine it (no apt-get and no
    # needs-restarting, first run without an OOM counter).
    report = {"uptime_seconds": 3600, "system_state": {"time_synchronized": False}}
    status, msg, metrics = SystemStateChecker().evaluate({}, report)
    assert (status, msg) == ("warning", "Clock not synchronized")
    assert metrics["_details"] == {
        **_NOTHING,
        "time_synchronized": False,
        "problems": ["time_sync"],
    }


@pytest.mark.parametrize(
    "report",
    [
        pytest.param({}, id="no-block"),
        pytest.param({"system_state": None}, id="null"),
        pytest.param({"system_state": {}}, id="empty"),
        pytest.param({"system_state": [_HEALTHY]}, id="list"),
        pytest.param({"system_state": "reboot"}, id="string"),
    ],
)
def test_a_report_without_a_block_is_not_evaluated(report):
    status, msg, metrics = SystemStateChecker().evaluate({}, report)
    assert (status, msg) == ("ok", "Not evaluated: no system state in report")
    assert metrics == {"_details": _NOTHING, "_objects": _UNREAD}


@pytest.mark.parametrize(
    "block",
    [
        pytest.param({"kernel": "6.12"}, id="unknown-key"),
        pytest.param(dict.fromkeys(_HEALTHY), id="all-null"),
        pytest.param(
            {
                "reboot_required": "true",
                "time_synchronized": 1,
                "security_updates": "3",
                "oom_kills": 2.5,
            },
            id="all-wrong-types",
        ),
    ],
)
def test_a_block_without_a_usable_field_counts_as_no_block(block):
    # Rated, such a block would read "System state OK" although nothing was determined.
    report = {"uptime_seconds": 3600, "system_state": block}
    status, msg, metrics = SystemStateChecker().evaluate({}, report)
    assert (status, msg) == ("ok", "Not evaluated: no system state in report")
    assert metrics == {"_details": _NOTHING, "_objects": _UNREAD}


def test_one_usable_field_is_enough_to_evaluate():
    report = {"system_state": {"reboot_required": "yes", "security_updates": 0}}
    status, msg, metrics = SystemStateChecker().evaluate({}, report)
    assert (status, msg) == ("ok", "System state OK")
    assert metrics == {
        "_details": {**_NOTHING, "security_updates": 0},
        "_objects": {"complete": False, "items": [_UPDATES_OK]},
    }


# --- the names behind the counts (R-1227) ---

_NAMED = {
    "security_packages": ["libssl3", "openssl"],
    "reboot_packages": ["linux-image-amd64"],
    "oom_processes": [{"pid": 4711, "name": "java"}, {"pid": 4712, "name": "node"}],
}

_ALL_OFF = {
    "check_reboot": False,
    "check_time_sync": False,
    "check_security_updates": False,
    "check_oom": False,
}


@pytest.mark.parametrize("config", [{}, _ALL_OFF], ids=["default", "switched-off"])
@pytest.mark.parametrize("fields", [_HEALTHY, _ALL_BAD], ids=["healthy", "all-bad"])
def test_the_names_go_into_details_only(config, fields):
    # Status and message stay those without the names: the message goes into mail and
    # webhook, the names only to the desktop.
    status, msg, metrics = _rate(config, **fields, **_NAMED)
    plain_status, plain_msg, plain = _rate(config, **fields)
    assert (status, msg) == (plain_status, plain_msg)
    assert metrics == {"_details": {**plain["_details"], **_NAMED}, "_objects": plain["_objects"]}
    for name in ("libssl3", "openssl", "linux-image-amd64", "java", "node", "4711"):
        assert name not in msg


@pytest.mark.parametrize("field", ["security_packages", "reboot_packages"])
@pytest.mark.parametrize(
    ("value", "shown"),
    [
        pytest.param("openssl", None, id="string"),
        pytest.param({"openssl": 1}, None, id="object"),
        pytest.param(3, None, id="number"),
        pytest.param(None, None, id="null"),
        pytest.param([], None, id="empty"),
        pytest.param(["", 5, None, ["x"], {"n": "x"}, True], None, id="no-string"),
        pytest.param(["openssl", 5, "", None, "curl"], ["openssl", "curl"], id="mixed"),
        pytest.param(["evil\nline\x1b[31m"], ["evil line [31m"], id="control-chars"),
        pytest.param(["x" * 600], ["x" * 499 + "…"], id="long"),
    ],
)
def test_a_name_list_keeps_only_strings_on_one_line(field, value, shown):
    status, msg, metrics = _rate(security_updates=3, **{field: value})
    assert (status, msg) == ("warning", "3 security updates pending")
    details = metrics["_details"]
    if shown is None:
        assert field not in details
    else:
        assert details[field] == shown


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        pytest.param("java", None, id="string"),
        pytest.param({"pid": 1, "name": "java"}, None, id="object"),
        pytest.param([], None, id="empty"),
        pytest.param(
            [
                "java",
                {"name": "no-pid"},
                {"pid": 0, "name": "pid-0"},
                {"pid": -1, "name": "negative"},
                {"pid": "12", "name": "pid-string"},
                {"pid": True, "name": "pid-bool"},
                {"pid": 1.5, "name": "pid-fraction"},
                {"pid": 12},
                {"pid": 13, "name": ""},
                {"pid": 14, "name": ["java"]},
            ],
            None,
            id="all-broken",
        ),
        pytest.param(
            [
                {"pid": 7, "name": "a\nb", "cmdline": "java -Dpass=x"},
                {"pid": 8},
                {"pid": 9, "name": "c"},
            ],
            [{"pid": 7, "name": "a b"}, {"pid": 9, "name": "c"}],
            id="mixed",
        ),
    ],
)
def test_oom_processes_keep_only_pid_and_name(value, shown):
    status, msg, metrics = _rate(oom_kills=2, oom_processes=value)
    assert (status, msg) == ("warning", "2 OOM kills since last report")
    details = metrics["_details"]
    if shown is None:
        assert "oom_processes" not in details
    else:
        assert details["oom_processes"] == shown


def test_at_most_100_names_and_10_oom_processes():
    names = [f"pkg{i:03d}" for i in range(150)]
    processes = [{"pid": pid, "name": f"p{pid}"} for pid in range(1, 20)]
    _, _, metrics = _rate(security_packages=names, reboot_packages=names, oom_processes=processes)
    details = metrics["_details"]
    assert details["security_packages"] == names[:100]
    assert details["reboot_packages"] == names[:100]
    assert details["oom_processes"] == processes[:10]
    assert_every_reader_reads(details)


def test_names_without_a_usable_count_count_as_no_block():
    status, msg, metrics = SystemStateChecker().evaluate({}, {"system_state": _NAMED})
    assert (status, msg) == ("ok", "Not evaluated: no system state in report")
    assert metrics == {"_details": _NOTHING, "_objects": _UNREAD}


# --- objects (R-1559): reboot, updates and clock per host ---


def test_every_bad_point_is_a_warning_object_with_its_value():
    _, _, metrics = _rate(**_ALL_BAD)
    assert _object_result(metrics) == (
        True,
        [
            _object("reboot", "Reboot", "warning", "Reboot required"),
            _object("updates", "Security updates", "warning", "3 security updates pending"),
            _object("clock", "Clock", "warning", "Clock not synchronized"),
        ],
    )


_TURNED_OFF = "Not rated, turned off in the check"


@pytest.mark.parametrize("fields", [_HEALTHY, _ALL_BAD], ids=["healthy", "all-bad"])
def test_a_switched_off_point_is_an_object_not_collected(fields):
    # A rule, not an absence: the host has the point, the check does not rate it.
    _, _, metrics = _rate(_ALL_OFF, **fields)
    assert _object_result(metrics) == (
        True,
        [
            _object("reboot", "Reboot", NOT_COLLECTED, _TURNED_OFF),
            _object("updates", "Security updates", NOT_COLLECTED, _TURNED_OFF),
            _object("clock", "Clock", NOT_COLLECTED, _TURNED_OFF),
        ],
    )


@pytest.mark.parametrize(
    ("switch", "index"),
    [("check_reboot", 0), ("check_security_updates", 1), ("check_time_sync", 2)],
)
def test_each_switch_turns_off_only_its_object(switch, index):
    _, _, metrics = _rate({switch: False}, **_ALL_BAD)
    statuses = [item["status"] for item in _object_result(metrics)[1]]
    expected = ["warning"] * 3
    expected[index] = NOT_COLLECTED
    assert statuses == expected


@pytest.mark.parametrize("value", ["false", 0, None])
def test_only_a_real_false_turns_an_object_off(value):
    _, _, metrics = _rate({"check_reboot": value}, reboot_required=True)
    assert _object_result(metrics)[1][0]["status"] == "warning"


@pytest.mark.parametrize(
    ("uptime", "clock"),
    [
        pytest.param(
            899, _object("clock", "Clock", "ok", "Not synchronized yet after boot"), id="grace"
        ),
        pytest.param(900, _object("clock", "Clock", "warning", "Clock not synchronized"), id="due"),
        pytest.param(
            None, _object("clock", "Clock", "warning", "Clock not synchronized"), id="no-uptime"
        ),
    ],
)
def test_the_clock_object_waits_out_the_grace_period(uptime, clock):
    _, _, metrics = _rate(uptime=uptime, time_synchronized=False)
    assert _object_result(metrics)[1][2] == clock


@pytest.mark.parametrize(
    "field", ["reboot_required", "time_synchronized", "security_updates", "oom_kills"]
)
def test_a_point_the_agent_left_out_makes_the_result_incomplete(field):
    # A field the agent could not read must not mark its object gone; the OOM count is none.
    block = {key: value for key, value in _HEALTHY.items() if key != field}
    report = {"uptime_seconds": 3600, "system_state": block}
    _, _, metrics = SystemStateChecker().evaluate({}, report)
    complete, items = _object_result(metrics)
    assert complete is (field == "oom_kills")
    assert len(items) == (3 if field == "oom_kills" else 2)


def test_a_partial_block_names_the_objects_it_holds():
    report = {"uptime_seconds": 3600, "system_state": {"time_synchronized": False}}
    _, _, metrics = SystemStateChecker().evaluate({}, report)
    assert _object_result(metrics) == (
        False,
        [_object("clock", "Clock", "warning", "Clock not synchronized")],
    )


# --- push path ---


def _add_system_state_check(factory):
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-s",
                server_id="srv-1",
                name="System State",
                check_type="system_state",
                config=json.dumps({}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()


def _stored(factory) -> tuple[str, str, dict]:
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-s").one()
        return state.status, state.message, json.loads(state.details)


def _stored_objects(factory) -> dict:
    with factory() as db:
        rows = db.query(MonitorObjectState).filter_by(check_id="chk-s").all()
        return {row.object_key: (row.status, row.gone_at is None) for row in rows}


def test_report_keeps_the_objects_while_the_block_is_missing(client_db):
    client, factory = client_db
    _add_system_state_check(factory)

    report = {"uptime_seconds": 3600, "system_state": {**_HEALTHY, "reboot_required": True}}
    assert client.post("/agent/srv-1/report", json=report).status_code == 200
    held = {
        "srv-1/reboot": ("warning", True),
        "srv-1/updates": ("ok", True),
        "srv-1/clock": ("ok", True),
    }
    assert _stored_objects(factory) == held

    # Nothing read is nothing gone: the objects stay as they were.
    assert client.post("/agent/srv-1/report", json={"uptime_seconds": 3600}).status_code == 200
    assert _stored_objects(factory) == held


def test_report_rates_a_system_state_check(client_db):
    client, factory = client_db
    _add_system_state_check(factory)

    report = {"uptime_seconds": 3600, "system_state": {**_HEALTHY, "reboot_required": True}}
    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200
    assert r.json()["checksUpdated"] == 1
    assert _stored(factory) == (
        "warning",
        "Reboot required",
        {**_HEALTHY, "reboot_required": True, "problems": ["reboot"]},
    )

    # A report without the block (an older agent) overwrites the values instead of
    # keeping the ones of the last report, already while the recovery hold
    # (consecutive_oks, default 2) keeps the reported warning standing.
    assert client.post("/agent/srv-1/report", json={"uptime_seconds": 3600}).status_code == 200
    assert _stored(factory) == (
        "warning",
        "Not evaluated: no system state in report (recovery 1/2)",
        _NOTHING,
    )
    assert client.post("/agent/srv-1/report", json={"uptime_seconds": 3600}).status_code == 200
    assert _stored(factory) == ("ok", "Not evaluated: no system state in report", _NOTHING)


def test_report_stores_the_names_in_details_not_in_the_message(client_db):
    client, factory = client_db
    _add_system_state_check(factory)

    fields = {**_HEALTHY, "security_updates": 2, **_NAMED}
    report = {"uptime_seconds": 3600, "system_state": fields}
    assert client.post("/agent/srv-1/report", json=report).status_code == 200
    assert _stored(factory) == (
        "warning",
        "2 security updates pending",
        {**fields, "problems": ["security_updates"]},
    )


def test_unusable_oom_processes_take_no_place_of_the_ten():
    junk = [{"pid": 0, "name": "junk"}] * 12
    processes = [{"pid": pid, "name": f"p{pid}"} for pid in range(1, 15)]
    _, _, metrics = _rate(oom_kills=2, oom_processes=[*junk, *processes])
    assert metrics["_details"]["oom_processes"] == processes[:10]
