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


def _rate(result, prev=None, stamp=STAMP, own=None, **config):
    report = {"probes": {"chk-p": result}}
    if stamp is not None:
        report["timestamp"] = stamp
    if own is not None:
        report["self"] = own
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
            "firing": [],
            "resting": [],
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
        ("not_allowed", "unknown", "The agent refused the target"),
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


def test_a_refusal_for_another_reason_names_no_foreign_address():
    # not_allowed covers every refusal of the guard (deny list, bound credential, foreign
    # address); the text must not claim one reason, the agent's error carries it.
    result = {"ts": T0, "status": "not_allowed", "error": "port 22 is never probed"}
    msg = _rate(result)[1]
    assert msg == "The agent refused the target: port 22 is never probed"
    assert "no address" not in msg


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


def _phase(factor):
    """The report's self block with the probe phase at factor."""
    entry = {"duration_ms": 40, "cpu_ms": 5, "timeouts": 0, "factor": factor, "throttled": False}
    return {"collectors": {"probes": entry}}


@pytest.mark.parametrize(
    ("factor", "interval", "age", "stale"),
    [
        (1, 300, 900, False),
        (1, 300, 901, True),
        (2, 300, 1500, False),
        (2, 300, 1501, True),
        (4, 300, 2700, False),
        (4, 300, 2701, True),
        (8, 900, 14700, False),
        (8, 900, 14701, True),
        # The agent never goes past 8: a larger factor is held to it.
        (64, 300, 5100, False),
        (64, 300, 5101, True),
    ],
)
def test_the_agents_probe_factor_stretches_the_freshness(factor, interval, age, stale):
    # The self-throttle runs every probe factor times less often (T9): its last result is
    # older, and the agent still runs it.
    result = _ok({"status_code": 200}, ts=T0 - age)
    level, msg, _ = _rate(result, own=_phase(factor), interval_s=interval)
    if stale:
        assert (level, msg) == (
            "unknown",
            f"Last probe result is {age // 60} min old; the agent no longer runs it",
        )
    else:
        assert level == "ok"


@pytest.mark.parametrize(
    "own",
    [
        "throttled",
        {"collectors": [{"probes": {"factor": 4}}]},
        {"collectors": {"probes": 4}},
        {"collectors": {"docker": {"factor": 8, "throttled": True}}},
        _phase("4"),
        _phase(True),
        _phase(None),
        _phase(math.inf),
        _phase(0),
        _phase(-4),
    ],
    ids=[
        "not an object",
        "a list",
        "no entry object",
        "another collector",
        "numeric string",
        "bool",
        "null",
        "infinite",
        "zero",
        "negative",
    ],
)
def test_without_a_usable_probe_factor_the_plain_interval_counts(own):
    assert _rate(_ok({"status_code": 200}, ts=T0 - 900), own=own)[0] == "ok"
    assert _rate(_ok({"status_code": 200}, ts=T0 - 901), own=own)[0] == "unknown"


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


@pytest.mark.parametrize(
    ("values", "want"),
    [
        # Kevin 2026-11-16 (R-1475): nothing to rate is ok.
        ({}, ("ok", "")),
        ({"f": 2}, ("ok", "")),
        ({"f": 9}, ("critical", "f = 9 (gt 5)")),
        # A value that is there but cannot be rated stays unknown.
        ({"f": "slow"}, ("unknown", "f: no usable value in the probe result")),
    ],
)
def test_a_rule_with_if_absent_ok_rates_a_missing_value_as_ok(values, want):
    rule = {**_rule("f", "gt", 5), "if_absent": "ok"}
    level, msg, _ = _rate(_ok(values), fields=["f"], rules=[rule])
    assert (level, msg if want[0] != "ok" else "") == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"on": False, "passive": True}, "ok"),
        ({"on": False, "passive": False}, "critical"),
        ({"on": False}, "critical"),
        # true is not 1.
        ({"on": False, "passive": 1}, "critical"),
        ({"on": True, "passive": False}, "ok"),
    ],
)
def test_a_rule_does_not_apply_while_its_unless_field_has_the_value(values, want):
    rule = {**_rule("on", "eq", False), "unless": {"field": "passive", "value": True}}
    level, _, _ = _rate(_ok(values), fields=["on", "passive"], rules=[rule])
    assert level == want


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


# --- hysteresis and conditions (R-1638) ---

_SLOW = {**_rule("duration_ms", "gt", 500, "warning"), "clear": 400}
_HYST = {"fields": ["duration_ms"], "rules": [_SLOW]}


def _stamp(offset):
    return datetime.fromtimestamp(T0 + offset, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(values, prev=None, offset=0, **config):
    """One measured run `offset` seconds after T0, rated in a report sent at that time."""
    return _rate(_ok(values, ts=T0 + offset), prev, _stamp(offset), **{**_HYST, **config})


def _details(rated):
    return rated[2]["_details"]


def test_a_rule_with_clear_holds_until_the_value_passes_clear():
    first = _run({"duration_ms": 600})
    assert first[:2] == ("warning", "duration_ms = 600 (gt 500)")
    assert _details(first)["firing"] == ["duration_ms.warning"]

    held = _run({"duration_ms": 450}, _details(first), 300)
    assert held[:2] == ("warning", "duration_ms = 450 (gt 500, clears at 400)")
    assert _details(held)["firing"] == ["duration_ms.warning"]

    # On clear itself the alerting case no longer holds: gt 400 is false at 400.
    cleared = _run({"duration_ms": 400}, _details(held), 600)
    assert cleared[0] == "ok"
    assert _details(cleared)["firing"] == []

    # Past clear the hysteresis ends; between clear and the limit the rule stays quiet.
    again = _run({"duration_ms": 450}, _details(cleared), 900)
    assert again[0] == "ok"


def test_without_a_firing_run_before_the_limit_counts():
    assert _run({"duration_ms": 450})[0] == "ok"
    assert _run({"duration_ms": 450}, {"firing": "duration_ms.warning"})[0] == "ok"


def test_a_rule_without_clear_has_no_hysteresis():
    rules = [_rule("duration_ms", "gt", 500, "warning")]
    first = _run({"duration_ms": 600}, rules=rules)
    assert _details(first)["firing"] == ["duration_ms.warning"]
    assert _run({"duration_ms": 450}, _details(first), 300, rules=rules)[0] == "ok"


def test_the_firing_rule_is_named_by_its_key():
    rules = [{**_SLOW, "key": "slow"}]
    first = _run({"duration_ms": 600}, rules=rules)
    assert _details(first)["firing"] == ["slow"]
    assert _run({"duration_ms": 450}, _details(first), 300, rules=rules)[0] == "warning"
    # The key of another rule does not hold this one.
    other = {**_details(first), "firing": ["duration_ms.warning"]}
    assert _run({"duration_ms": 450}, other, 300, rules=rules)[0] == "ok"


def test_the_same_run_sent_again_keeps_its_rating():
    first = _run({"duration_ms": 600})
    held = _run({"duration_ms": 450}, _details(first), 300)
    resent = _rate(_ok({"duration_ms": 450}, ts=T0 + 300), _details(held), _stamp(600), **_HYST)
    assert resent[:2] == held[:2]
    assert _details(resent)["firing"] == ["duration_ms.warning"]


@pytest.mark.parametrize(
    ("result", "level"),
    [
        ({"status": "error", "error": "timeout"}, "critical"),
        ({"status": "denied", "error": ""}, "warning"),
        ({"status": "weird"}, "unknown"),
    ],
)
def test_a_run_without_a_rating_keeps_the_hysteresis(result, level):
    first = _run({"duration_ms": 600})
    gap = _rate({"ts": T0 + 300, **result}, _details(first), _stamp(300), **_HYST)
    assert gap[0] == level
    assert _details(gap)["firing"] == ["duration_ms.warning"]
    assert _run({"duration_ms": 450}, _details(gap), 600)[0] == "warning"


def test_a_stale_run_keeps_the_hysteresis():
    first = _run({"duration_ms": 600})
    stale = _rate(_ok({"duration_ms": 450}, ts=T0), _details(first), _stamp(901), **_HYST)
    assert stale[0] == "unknown"
    assert _details(stale)["firing"] == ["duration_ms.warning"]


def test_a_rule_without_a_value_keeps_the_hysteresis():
    first = _run({"duration_ms": 600})
    gap = _run({}, _details(first), 300)
    assert gap[:2] == ("unknown", "duration_ms: no usable value in the probe result")
    assert _details(gap)["firing"] == ["duration_ms.warning"]
    assert _run({"duration_ms": 450}, _details(gap), 600)[0] == "warning"


def test_an_absent_value_rated_ok_keeps_the_hysteresis():
    rules = [{**_SLOW, "if_absent": "ok"}]
    first = _run({"duration_ms": 600}, rules=rules)
    gap = _run({}, _details(first), 300, rules=rules)
    assert gap[0] == "ok"
    assert _details(gap)["firing"] == ["duration_ms.warning"]


@pytest.mark.parametrize("firing", [None, "x", [1, None], {"duration_ms.warning": 1}])
def test_unusable_firing_means_none(firing):
    first = _details(_run({"duration_ms": 600}))
    assert _run({"duration_ms": 450}, {**first, "firing": firing}, 300)[0] == "ok"


_GATED = {
    "fields": ["status_code", "duration_ms"],
    "rules": [
        {
            **_rule("duration_ms", "gt", 500, "warning"),
            "when": {"field": "status_code", "op": "eq", "value": 200},
        }
    ],
}


def test_a_rule_rests_while_its_condition_on_the_own_result_fails():
    rested = _run({"status_code": 503, "duration_ms": 900}, **_GATED)
    assert rested[0] == "ok"
    when = {"field": "status_code", "op": "eq", "value": 200}
    assert _details(rested)["resting"] == [{"key": "duration_ms.warning", "when": when}]
    assert _details(rested)["firing"] == []

    rated = _run({"status_code": 200, "duration_ms": 900}, **_GATED)
    assert rated[:2] == ("warning", "duration_ms = 900 (gt 500)")
    assert _details(rated)["resting"] == []


@pytest.mark.parametrize("status_code", [None, [200]])
def test_a_condition_without_a_usable_value_lets_the_rule_rate(status_code):
    values = {"duration_ms": 900}
    if status_code is not None:
        values["status_code"] = status_code
    rated = _run(values, **_GATED)
    assert rated[0] == "warning"
    assert _details(rated)["resting"] == []


def test_a_text_is_a_value_the_condition_tells():
    # eq 200 is told on "200x" and fails: the rule rests.
    rated = _run({"status_code": "200x", "duration_ms": 900}, **_GATED)
    assert rated[0] == "ok"
    assert [r["key"] for r in _details(rated)["resting"]] == ["duration_ms.warning"]


def test_a_resting_rule_ends_its_hysteresis():
    rules = [{**_SLOW, "when": {"field": "status_code", "op": "eq", "value": 200}}]
    config = {"fields": ["status_code", "duration_ms"], "rules": rules}
    first = _run({"status_code": 200, "duration_ms": 600}, **config)
    assert _details(first)["firing"] == ["duration_ms.warning"]
    rested = _run({"status_code": 503, "duration_ms": 450}, _details(first), 300, **config)
    assert _details(rested)["firing"] == []
    back = _run({"status_code": 200, "duration_ms": 450}, _details(rested), 600, **config)
    assert back[0] == "ok"


def test_a_probe_error_is_critical_whatever_the_condition_says():
    error = {"ts": T0, "status": "error", "error": "refused"}
    assert _rate(error, **_GATED)[:2] == ("critical", "Probe failed: refused")


_ON_MAIL = {
    "fields": ["duration_ms"],
    "rules": [
        {
            **_rule("duration_ms", "gt", 500, "warning"),
            "when": {"field": "ok", "op": "eq", "value": True, "check": "test_mail"},
        }
    ],
}


def _sibling(ok, age=60, interval_s=300):
    return {"test_mail": {"values": {"ok": ok}, "measured_ts": T0 - age, "interval_s": interval_s}}


def test_a_rule_rests_while_its_condition_on_a_sibling_fails():
    rested = _run({"duration_ms": 900}, _siblings=_sibling(False), **_ON_MAIL)
    assert rested[0] == "ok"
    assert [r["key"] for r in _details(rested)["resting"]] == ["duration_ms.warning"]
    assert _run({"duration_ms": 900}, _siblings=_sibling(True), **_ON_MAIL)[0] == "warning"


@pytest.mark.parametrize(
    ("interval_s", "age", "rests"),
    [(300, 900, True), (300, 901, False), (3600, 7500, True), (3600, 7501, False)],
)
def test_a_sibling_counts_while_its_result_is_fresh_by_its_interval(interval_s, age, rests):
    siblings = _sibling(False, age=age, interval_s=interval_s)
    level = _run({"duration_ms": 900}, _siblings=siblings, **_ON_MAIL)[0]
    assert level == ("ok" if rests else "warning")


def test_the_agents_probe_factor_stretches_the_siblings_freshness():
    siblings = _sibling(False, age=2 * 300 * 2 + 300)
    report = {"collectors": {"probes": {"factor": 2}}}
    result = _ok({"duration_ms": 900})
    rated = _rate(result, None, STAMP, report, **_ON_MAIL, _siblings=siblings)
    assert rated[0] == "ok"
    assert _rate(result, None, STAMP, None, **_ON_MAIL, _siblings=siblings)[0] == "warning"


@pytest.mark.parametrize(("age", "rests"), [(600, True), (601, False)])
def test_max_age_bounds_the_siblings_age(age, rests):
    rules = [{**_ON_MAIL["rules"][0]}]
    rules[0]["when"] = {**rules[0]["when"], "max_age": 600}
    siblings = _sibling(False, age=age)
    level = _run({"duration_ms": 900}, _siblings=siblings, **{**_ON_MAIL, "rules": rules})[0]
    assert level == ("ok" if rests else "warning")


@pytest.mark.parametrize(
    "siblings",
    [
        None,
        {},
        {"test_mail": "garbage"},
        {"test_mail": {"values": {"ok": False}}},
        {"test_mail": {"values": {"ok": False}, "measured_ts": "T0"}},
        {"test_mail": {"values": "garbage", "measured_ts": T0}},
        {"test_mail": {"values": {}, "measured_ts": T0}},
        {"other": {"values": {"ok": False}, "measured_ts": T0}},
    ],
)
def test_a_sibling_that_cannot_tell_lets_the_rule_rate(siblings):
    config = {**_ON_MAIL} if siblings is None else {**_ON_MAIL, "_siblings": siblings}
    rated = _run({"duration_ms": 900}, **config)
    assert rated[0] == "warning"
    assert _details(rated)["resting"] == []


def test_firing_and_resting_are_empty_on_a_plain_result():
    details = _details(_rate(_ok({"status_code": 200})))
    assert (details["firing"], details["resting"]) == ([], [])


# --- the check rests as a whole (R-1825) ---

_BACKUP = {"field": "backup", "op": "eq", "value": False, "check": "aio"}
_STATUS = {
    "fields": ["status_code", "maintenance"],
    "rules": [_rule("status_code", "ne", 200), _rule("maintenance", "eq", True, "warning")],
    "when": _BACKUP,
}
_FAILED = {"ts": T0, "status": "error", "error": "connection refused"}
_RESTING = [
    {"key": "status_code.critical", "when": _BACKUP},
    {"key": "maintenance.warning", "when": _BACKUP},
]
# The details of a rated run five minutes before, with a rule that held.
_BEFORE = {
    "ts": T0 - 300,
    "status": "ok",
    "measured_ts": T0 - 300,
    "values": {"status_code": 503, "maintenance": False},
    "baseline": {"status_code": 200, "maintenance": False},
    "firing": ["status_code.critical"],
}


def _aio(backup, age=60, interval_s=300):
    return {
        "aio": {"values": {"backup": backup}, "measured_ts": T0 - age, "interval_s": interval_s}
    }


@pytest.mark.parametrize(
    ("error", "text"),
    [("connection refused", "Probe failed: connection refused"), ("", "Probe failed")],
)
def test_a_failed_run_rests_while_the_condition_fails(error, text):
    level, msg, metrics = _rate(
        {**_FAILED, "error": error}, _BEFORE, _siblings=_aio(True), **_STATUS
    )
    assert (level, msg) == ("ok", f"Resting (aio.backup = true): {text}")
    details = metrics["_details"]
    assert (details["problems"], details["firing"]) == ([], [])
    assert details["resting"] == _RESTING
    # A failed run measures nothing: the last measured run stays.
    assert details["measured_ts"] == T0 - 300
    assert details["values"] == _BEFORE["values"]
    assert details["baseline"] == _BEFORE["baseline"]
    assert (details["status"], details["ts"]) == ("error", T0)


def test_a_measured_run_rests_and_keeps_its_values():
    result = _ok({"status_code": 503, "maintenance": True})
    level, msg, metrics = _rate(result, _BEFORE, _siblings=_aio(True), **_STATUS)
    assert (level, msg) == (
        "ok",
        "Resting (aio.backup = true): OK: status_code = 503, maintenance = true",
    )
    details = metrics["_details"]
    assert (details["problems"], details["firing"]) == ([], [])
    assert details["resting"] == _RESTING
    # Stored as if rated: the run before becomes the baseline of the next one.
    assert details["measured_ts"] == T0
    assert details["values"] == {"status_code": 503, "maintenance": True}
    assert details["baseline"] == _BEFORE["values"]


def test_a_resting_check_without_values_says_so():
    rated = _rate(_ok({}), _siblings=_aio(True), **{**_STATUS, "fields": []})
    assert rated[:2] == ("ok", "Resting (aio.backup = true): Probe OK")


def test_the_check_rates_while_the_condition_holds():
    siblings = _aio(False)
    assert _rate(_FAILED, _BEFORE, _siblings=siblings, **_STATUS)[:2] == (
        "critical",
        "Probe failed: connection refused",
    )
    rated = _rate(_ok({"status_code": 503, "maintenance": True}), _siblings=siblings, **_STATUS)
    assert rated[0] == "critical"
    assert _details(rated)["resting"] == []
    assert _details(rated)["firing"] == ["status_code.critical", "maintenance.warning"]


@pytest.mark.parametrize(
    ("when", "siblings"),
    [
        (_BACKUP, None),
        (_BACKUP, {}),
        (_BACKUP, {"aio": "garbage"}),
        (_BACKUP, {"aio": {"values": {}, "measured_ts": T0, "interval_s": 300}}),
        (_BACKUP, {"aio": {"values": {"backup": True}, "interval_s": 300}}),
        (_BACKUP, {"other": _aio(True)["aio"]}),
        # Older than two intervals and a run of the sibling.
        (_BACKUP, _aio(True, age=901)),
        (_BACKUP, _aio(True, age=7501, interval_s=3600)),
        ({**_BACKUP, "max_age": 600}, _aio(True, age=601)),
        # Not a condition at all: as if there were none.
        ("garbage", _aio(True)),
        ({**_BACKUP, "check": None}, _aio(True)),
    ],
)
def test_a_condition_that_cannot_be_told_lets_the_check_rate(when, siblings):
    config = {**_STATUS, "when": when}
    if siblings is not None:
        config["_siblings"] = siblings
    level, msg, metrics = _rate(_FAILED, _BEFORE, **config)
    assert (level, msg) == ("critical", "Probe failed: connection refused")
    assert metrics["_details"]["resting"] == []
    assert metrics["_details"]["firing"] == _BEFORE["firing"]


@pytest.mark.parametrize(
    ("when", "age", "interval_s"),
    [
        (_BACKUP, 900, 300),
        (_BACKUP, 7500, 3600),
        ({**_BACKUP, "max_age": 600}, 600, 300),
        ({**_BACKUP, "max_age": 3600}, 3600, 300),
    ],
)
def test_a_fresh_enough_condition_rests_the_check(when, age, interval_s):
    siblings = _aio(True, age=age, interval_s=interval_s)
    rated = _rate(_FAILED, _siblings=siblings, **{**_STATUS, "when": when})
    assert rated[:2] == ("ok", "Resting (aio.backup = true): Probe failed: connection refused")


def test_the_agents_probe_factor_stretches_the_conditions_freshness():
    siblings = _aio(True, age=2 * 300 * 2 + 300)
    rated = _rate(_FAILED, None, STAMP, _phase(2), _siblings=siblings, **_STATUS)
    assert rated[0] == "ok"
    assert _rate(_FAILED, _siblings=siblings, **_STATUS)[0] == "critical"


@pytest.mark.parametrize(
    ("result", "level", "text"),
    [
        (
            {"ts": T0, "status": "no_credential", "error": ""},
            "warning",
            "No credential stored on the host for this check",
        ),
        ({"ts": T0, "status": "weird"}, "unknown", 'Unknown probe status "weird"'),
        ({**_FAILED, "ts": None}, "unknown", "Probe result without a time"),
        (
            {**_FAILED, "ts": T0 - 1000},
            "unknown",
            "Last probe result is 16 min old; the agent no longer runs it",
        ),
    ],
)
def test_what_comes_before_the_rules_stays_before_the_condition(result, level, text):
    rated = _rate(result, _BEFORE, _siblings=_aio(True), **_STATUS)
    assert rated[:2] == (level, text)
    assert _details(rated)["resting"] == []


def test_a_resting_check_ends_its_hysteresis():
    config = {"fields": ["duration_ms"], "rules": [_SLOW], "when": _BACKUP}
    first = _run({"duration_ms": 600}, _siblings=_aio(False), **config)
    assert _details(first)["firing"] == ["duration_ms.warning"]
    failed = {**_FAILED, "ts": T0 + 300}
    rested = _rate(failed, _details(first), _stamp(300), _siblings=_aio(True, age=-240), **config)
    assert rested[0] == "ok"
    assert _details(rested)["firing"] == []
    after = _aio(False, age=-540)
    assert _run({"duration_ms": 450}, _details(rested), 600, _siblings=after, **config)[0] == "ok"
    # Without the rest the rule would still hold, on the wrong side of clear.
    held = _run({"duration_ms": 450}, _details(first), 600, _siblings=after, **config)
    assert held[0] == "warning"


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
