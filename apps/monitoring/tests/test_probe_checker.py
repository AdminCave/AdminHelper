# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""probe (R-1223): the agent's status of a probe first, then freshness by the probe's
interval, then the rules on the values, the worst level that holds winning; delta rules
compare with the run before, also when the same run comes again in the next report."""

import json
import math
import time
from datetime import UTC, datetime

import pytest

from app.check_types import PUSH_ONLY_TYPES
from app.checkers import get_checker
from app.checkers.probe import ProbeChecker
from app.models import MonitorCheck, MonitorState

# Far from the test machine's clock, so only the report's own time can make a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"

_CONFIG = {
    "_check_id": "chk-p",
    "sensor": "http",
    "interval_s": 300,
    "fields": ["status_code", "duration_ms"],
    "rules": [],
}


def _rule(field, op, value, level="critical"):
    return {"field": field, "op": op, "value": value, "level": level}


def _rate(result, prev=None, stamp=STAMP, **config):
    report = {"probes": {"chk-p": result}}
    if stamp is not None:
        report["timestamp"] = stamp
    return ProbeChecker().evaluate({**_CONFIG, **config}, report, prev)


def _ok(values, ts=T0):
    return {"ts": ts, "duration_ms": 12, "status": "ok", "values": values, "error": ""}


def test_run_waits_for_agent_data():
    assert ProbeChecker().run({}) == ("unknown", "Waiting for agent data", None)


def test_registered_as_push_type():
    assert "probe" in PUSH_ONLY_TYPES
    assert isinstance(get_checker("probe"), ProbeChecker)


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"probes": None},
        {"probes": {"other": _ok({})}},
        {"probes": {"chk-p": "ok"}},
        {"probes": ["chk-p"]},
    ],
    ids=["no block", "null block", "other id", "not an object", "a list"],
)
def test_no_result_leaves_the_details_alone(report):
    # No details: the push path keeps the stored ones (keep_previous_details_when_absent).
    assert ProbeChecker().evaluate(_CONFIG, report) == (
        "unknown",
        "No result for this probe in the agent report",
        None,
    )


def test_ok_result_shows_the_values():
    status, msg, metrics = _rate(_ok({"status_code": 200, "duration_ms": 31.5}))
    assert (status, msg) == ("ok", "OK: status_code = 200, duration_ms = 31.5")
    assert metrics == {
        "_details": {
            "ts": T0,
            "status": "ok",
            "error": None,
            "measured_ts": T0,
            "values": {"status_code": 200, "duration_ms": 31.5},
            "baseline": None,
            "problems": [],
        }
    }


def test_ok_without_values_says_so():
    assert _rate(_ok({}), fields=[])[:2] == ("ok", "Probe OK")


@pytest.mark.parametrize(
    ("status", "level", "text"),
    [
        (
            "denied",
            "warning",
            "Access denied (401/403); the agent waits until the credential changes",
        ),
        ("no_credential", "warning", "No credential stored on the host for this check"),
        ("not_allowed", "unknown", "Target is no address of this host; the agent refused it"),
        ("unsupported", "unknown", "Sensor not supported on this host"),
        (
            "ambiguous_target",
            "unknown",
            "Target listens on several ports and none matches the hint",
        ),
        ("invalid", "unknown", "Agent rejected the probe parameters"),
    ],
)
def test_a_probe_the_agent_did_not_run_says_why(status, level, text):
    result = {"ts": T0, "status": status, "values": {"status_code": 200}, "error": ""}
    got_level, msg, metrics = _rate(result)
    assert (got_level, msg) == (level, text)
    # Values of a run that did not measure are not taken.
    assert metrics["_details"]["values"] == {}
    assert metrics["_details"]["problems"] == [text]

    result["error"] = "port 8000\nforged line"
    assert _rate(result)[1] == f"{text}: port 8000 forged line"


def test_not_run_keeps_the_values_of_the_last_measured_run():
    first = _rate(_ok({"status_code": 200}))[2]["_details"]
    denied = {"ts": T0 + 300, "status": "denied", "error": ""}
    details = _rate(denied, prev=first, stamp="2020-01-01T12:05:00Z")[2]["_details"]
    assert (details["ts"], details["measured_ts"]) == (T0 + 300, T0)
    assert details["values"] == {"status_code": 200}


@pytest.mark.parametrize(
    ("status", "shown"), [("weird", '"weird"'), (5, "null"), (None, "null"), ([1], "null")]
)
def test_unknown_status_is_unknown(status, shown):
    level, msg, _ = _rate({"ts": T0, "status": status})
    assert (level, msg) == ("unknown", f"Unknown probe status {shown}")


@pytest.mark.parametrize("ts", [None, "1762700000", True, math.inf])
def test_result_without_a_usable_time_is_unknown(ts):
    assert _rate({**_ok({}), "ts": ts})[:2] == ("unknown", "Probe result without a time")


@pytest.mark.parametrize(
    ("interval", "age", "stale"),
    [(300, 900, False), (300, 901, True), (3600, 7500, False), (3600, 7501, True)],
)
def test_result_older_than_two_intervals_and_a_run_is_stale(interval, age, stale):
    level, msg, metrics = _rate(_ok({"status_code": 200}, ts=T0 - age), interval_s=interval)
    if stale:
        assert level == "unknown"
        assert msg == f"Last probe result is {age // 60} min old; the agent no longer runs it"
        # A stale result is no measurement either.
        assert metrics["_details"]["values"] == {}
    else:
        assert level == "ok"


def test_stale_error_is_unknown_not_critical():
    stale = {"ts": T0 - 1000, "status": "error", "error": "connection refused"}
    assert _rate(stale)[0] == "unknown"


def test_freshness_counts_by_the_agents_clock():
    # The host's clock runs an hour behind: report and probe come from the same clock.
    assert _rate(_ok({"status_code": 200}, ts=T0 - 3600), stamp="2020-01-01T11:00:00Z")[0] == "ok"


@pytest.mark.parametrize("stamp", [None, "yesterday", "2020-01-01T12:00:00", T0])
def test_without_a_usable_report_time_the_server_clock_counts(stamp):
    now = time.time()
    assert _rate(_ok({"status_code": 200}, ts=now - 10), stamp=stamp)[0] == "ok"
    assert _rate(_ok({"status_code": 200}, ts=now - 1000), stamp=stamp)[0] == "unknown"


def test_error_is_critical_with_the_agents_reason():
    result = {"ts": T0, "status": "error", "error": "connection refused"}
    assert _rate(result)[:2] == ("critical", "Probe failed: connection refused")
    assert _rate({**result, "error": ""})[:2] == ("critical", "Probe failed")


def test_only_asked_scalar_fields_are_kept():
    values = {
        "status_code": 200,
        "duration_ms": math.nan,
        "data.text": "x" * 300 + "\n",
        "data.flag": False,
        "data.obj": {"nested": 1},
        "data.list": [1],
        "data.big": 10**400,
        "secret": "not asked",
    }
    fields = ["status_code", "duration_ms", "data.text", "data.flag", "data.obj", "data.list"]
    details = _rate(_ok(values), fields=[*fields, "data.big", "missing"])[2]["_details"]
    assert details["values"] == {"status_code": 200, "data.text": "x" * 256, "data.flag": False}


@pytest.mark.parametrize(
    ("value", "rule", "holds"),
    [
        (200, _rule("f", "eq", 200), True),
        (200, _rule("f", "eq", "200"), False),
        (1, _rule("f", "eq", True), False),
        (True, _rule("f", "eq", True), True),
        (500, _rule("f", "ne", 200), True),
        (200, _rule("f", "ne", 200), False),
        (True, _rule("f", "ne", 1), True),
        ("failed", _rule("f", "in", ["failed", "dead"]), True),
        ("active", _rule("f", "in", ["failed", "dead"]), False),
        (1, _rule("f", "in", [True]), False),
        (4, _rule("f", "lt", 5), True),
        (5, _rule("f", "lt", 5), False),
        (5, _rule("f", "le", 5), True),
        (6, _rule("f", "gt", 5), True),
        (5, _rule("f", "gt", 5), False),
        (5, _rule("f", "ge", 5), True),
        (4.5, _rule("f", "ge", 5), False),
        (T0 - 3601, _rule("f", "max_age", 3600), True),
        (T0 - 3600, _rule("f", "max_age", 3600), False),
    ],
)
def test_rule_ops(value, rule, holds):
    level, msg, _ = _rate(_ok({"f": value}), fields=["f"], rules=[rule])
    if holds:
        assert level == "critical"
        assert msg.startswith("f ")
    else:
        assert level == "ok"


def test_rule_messages_name_the_field_and_the_rule():
    rules = [_rule("code", "ne", 200), _rule("since", "max_age", 3600)]
    values = {"code": 503, "since": T0 - 4000}
    msg = _rate(_ok(values), fields=["code", "since"], rules=rules)[1]
    assert msg == "code = 503 (ne 200); since is 4000 s old (max_age 3600)"


@pytest.mark.parametrize(
    ("value", "rule"),
    [
        ("slow", _rule("f", "gt", 5)),
        (True, _rule("f", "lt", 5)),
        ("old", _rule("f", "max_age", 60)),
        (None, _rule("f", "eq", 200)),
    ],
)
def test_a_value_the_rule_cannot_rate_is_unknown(value, rule):
    values = {} if value is None else {"f": value}
    level, msg, metrics = _rate(_ok(values), fields=["f"], rules=[rule])
    assert (level, msg) == ("unknown", "f: no usable value in the probe result")
    assert metrics["_details"]["problems"] == [msg]


def test_the_worst_level_that_holds_wins_and_all_are_named():
    rules = [
        _rule("a", "gt", 1, "warning"),
        _rule("b", "gt", 1, "critical"),
        _rule("c", "gt", 1, "warning"),
        _rule("missing", "gt", 1, "critical"),
    ]
    level, msg, _ = _rate(_ok({"a": 2, "b": 2, "c": 0}), fields=["a", "b", "c"], rules=rules)
    assert (level, msg) == ("critical", "a = 2 (gt 1); b = 2 (gt 1)")
    level, msg, _ = _rate(_ok({"a": 2, "b": 0}), fields=["a", "b"], rules=rules[:2])
    assert (level, msg) == ("warning", "a = 2 (gt 1)")


def test_delta_compares_with_the_run_before():
    rules = [_rule("restarts", "delta_gt", 2, "warning")]
    rate = {"fields": ["restarts"], "rules": rules}

    # The first run has nothing to compare with: no problem.
    first = _rate(_ok({"restarts": 5}), **rate)
    assert first[0] == "ok"
    assert first[2]["_details"]["baseline"] is None

    later = "2020-01-01T12:05:00Z"
    second = _rate(_ok({"restarts": 8}, ts=T0 + 300), first[2]["_details"], later, **rate)
    assert second[:2] == ("warning", "restarts rose by 3 (delta_gt 2)")
    assert second[2]["_details"]["baseline"] == {"restarts": 5}

    # The same run again in the next report keeps its baseline: the rise still shows.
    again = "2020-01-01T12:10:00Z"
    third = _rate(_ok({"restarts": 8}, ts=T0 + 300), second[2]["_details"], again, **rate)
    assert third[:2] == second[:2]
    assert third[2]["_details"]["baseline"] == {"restarts": 5}

    # A new run compares with the one before it, not with the first.
    fourth = _rate(_ok({"restarts": 9}, ts=T0 + 600), third[2]["_details"], again, **rate)
    assert fourth[0] == "ok"
    assert fourth[2]["_details"]["baseline"] == {"restarts": 8}


def test_a_counter_that_went_down_is_no_rise():
    rate = {"fields": ["restarts"], "rules": [_rule("restarts", "delta_gt", 0)]}
    prev = _rate(_ok({"restarts": 7}), **rate)[2]["_details"]
    later = "2020-01-01T12:05:00Z"
    assert _rate(_ok({"restarts": 0}, ts=T0 + 300), prev, later, **rate)[0] == "ok"


@pytest.mark.parametrize("prev", [None, {}, {"values": "x", "measured_ts": "y"}, "garbage"])
def test_unusable_previous_details_mean_no_baseline(prev):
    rate = {"fields": ["restarts"], "rules": [_rule("restarts", "delta_gt", 0)]}
    level, _, metrics = _rate(_ok({"restarts": 9}), prev, **rate)
    assert level == "ok"
    assert metrics["_details"]["baseline"] is None


# --- push path ---


def _add_probe_check(factory, check_id, config):
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                server_id="srv-1",
                name=check_id,
                check_type="probe",
                config=json.dumps(config),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()


def _stored(factory, check_id) -> tuple[str, str, dict]:
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id=check_id).one()
        return state.status, state.message, json.loads(state.details)


def test_report_rates_each_probe_check_by_its_own_id(client_db):
    client, factory = client_db
    config = {
        "sensor": "http",
        "target": {"kind": "port", "port_hint": 8000, "scheme": "http"},
        "fields": ["status_code"],
        "rules": [_rule("status_code", "ne", 200)],
    }
    _add_probe_check(factory, "chk-a", config)
    _add_probe_check(factory, "chk-b", config)
    now = int(time.time())
    report = {
        "probes": {
            "chk-a": _ok({"status_code": 200}, ts=now),
            "chk-b": _ok({"status_code": 503}, ts=now),
        }
    }

    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200
    assert r.json()["checksUpdated"] == 2
    assert _stored(factory, "chk-a")[:2] == ("ok", "OK: status_code = 200")
    status, msg, details = _stored(factory, "chk-b")
    assert (status, msg) == ("critical", "status_code = 503 (ne 200)")
    assert details["values"] == {"status_code": 503}

    # A report without the probe keeps the details of the last result.
    assert client.post("/agent/srv-1/report", json={"probes": {}}).status_code == 200
    status, msg, kept = _stored(factory, "chk-b")
    assert msg.startswith("No result for this probe in the agent report")
    assert kept == details
