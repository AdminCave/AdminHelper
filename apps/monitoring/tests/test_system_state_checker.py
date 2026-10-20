# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""system_state (R-0423): the four points of the agent's system_state block, each at most a
warning, each switchable; the clock only after 15 min of uptime; anything but a JSON bool or a
whole JSON number counts as missing; a report without the block is not evaluated."""

import json

import pytest

from app.check_types import PUSH_ONLY_TYPES
from app.checkers import get_checker
from app.checkers.system import SystemStateChecker
from app.models import MonitorCheck, MonitorState

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
    assert metrics == {"_details": {**_HEALTHY, "problems": []}}


@pytest.mark.parametrize(
    ("fields", "message", "problem"),
    [
        pytest.param({"reboot_required": True}, "Reboot required", "reboot", id="reboot"),
        pytest.param(
            {"time_synchronized": False}, "Clock not synchronized", "time_sync", id="time-sync"
        ),
        pytest.param(
            {"security_updates": 3},
            "3 security updates pending",
            "security_updates",
            id="security-updates",
        ),
        pytest.param({"oom_kills": 2}, "2 OOM kills since last report", "oom", id="oom"),
    ],
)
def test_each_point_alone_is_a_warning(fields, message, problem):
    status, msg, metrics = _rate(**fields)
    assert (status, msg) == ("warning", message)
    assert metrics == {"_details": {**_HEALTHY, **fields, "problems": [problem]}}


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
    assert metrics == {"_details": _NOTHING}


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
    assert metrics == {"_details": _NOTHING}


def test_one_usable_field_is_enough_to_evaluate():
    report = {"system_state": {"reboot_required": "yes", "security_updates": 0}}
    status, msg, metrics = SystemStateChecker().evaluate({}, report)
    assert (status, msg) == ("ok", "System state OK")
    assert metrics == {"_details": {**_NOTHING, "security_updates": 0}}


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
