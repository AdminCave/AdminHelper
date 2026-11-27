# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Probe checker.

Rates one probe of the agent (R-1223): a sensor compiled into the agent, run against a
module instance with the parameters of the check's config. The agent sends the last
result of every probe in each report, filed under the check id, with the time it ran;
so this checker needs no state beyond the previous details (delta rules).

Order: the agent's own status first (a probe it did not run says why), then freshness
(a result older than two intervals plus one agent run means the probe stopped; the agent's
self-throttle stretches the interval by its probe factor), then the rules on the values. A
rule describes the alerting case; the worst level that holds wins. A rule with `clear` that
held in the run before holds until the value passes clear (R-1638); a rule with `when` rests
while its condition is told and does not hold. A check with `when` rests as a whole the same
way, before an error of the run: `ok`, with the run's outcome in the message (R-1825).
"""

from __future__ import annotations

import json
import operator
import time
from datetime import datetime
from typing import NamedTuple

from app.checkers.agent import agent_number, cap_agent_text, join_capped

# The agent runs every 5 min and runs the probes that are due in that run.
AGENT_RUN_S = 300
DEFAULT_INTERVAL_S = 300
# The agent's self-throttle runs its probes up to this many times less often.
MAX_PROBE_FACTOR = 8
# The agent cuts a text value to this length; a value from the report is not trusted to.
MAX_VALUE_TEXT = 256

# The agent did not run the probe, and says why. Warning where the admin has to act on this
# host (store or renew a credential), unknown where nothing was measured.
_NOT_RUN: dict[str, tuple[str, str]] = {
    "denied": (
        "warning",
        "Access denied (401/403); the agent waits until the credential changes",
    ),
    "no_credential": ("warning", "No credential stored on the host for this check"),
    "not_allowed": ("unknown", "The agent refused the target"),
    "unsupported": ("unknown", "Sensor not supported on this host"),
    "ambiguous_target": ("unknown", "Target listens on several ports and none matches the hint"),
    "invalid": ("unknown", "Agent rejected the probe parameters"),
}
_LEVELS = {"info": 0, "warning": 1, "critical": 2}
_LEVEL_NAMES = {n: name for name, n in _LEVELS.items()}
_COMPARE = {"lt": operator.lt, "le": operator.le, "gt": operator.gt, "ge": operator.ge}


def _shown(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _same(a: object, b: object) -> bool:
    """Equal as JSON values: true is not 1, and "200" is not 200."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    return a == b


def _values(raw: object, fields: object) -> dict:
    """The values of the asked fields that are scalars, texts cut; nothing else of the
    result is kept (the agent's field release is checked here again)."""
    if not isinstance(raw, dict) or not isinstance(fields, list):
        return {}
    values: dict = {}
    for field in fields:
        if not isinstance(field, str) or field not in raw:
            continue
        value = raw[field]
        if isinstance(value, bool):
            values[field] = value
        elif (number := agent_number(value)) is not None:
            values[field] = number
        elif isinstance(value, str):
            values[field] = value[:MAX_VALUE_TEXT]
    return values


def _report_time(report: dict) -> float:
    """When the agent sent the report, by its own clock: the probe's ts comes from the same
    clock, so a host whose clock is off does not make every probe look stale."""
    stamp = report.get("timestamp")
    if isinstance(stamp, str):
        try:
            parsed = datetime.fromisoformat(stamp)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            return parsed.timestamp()
    return time.time()


def _stale_after(interval_s: object, factor: int) -> float:
    """Seconds after which a probe's result counts as stopped: two intervals, stretched by the
    agent's probe factor, plus one agent run."""
    interval = agent_number(interval_s) or DEFAULT_INTERVAL_S
    return 2 * interval * factor + AGENT_RUN_S


def _probe_factor(report: dict) -> int:
    """How many times less often the agent runs its probes while its self-throttle holds
    them back: the probe phase's factor in the same report, held to 1..MAX_PROBE_FACTOR;
    1 without one (an agent before report v4)."""
    own = report.get("self")
    collectors = own.get("collectors") if isinstance(own, dict) else None
    phase = collectors.get("probes") if isinstance(collectors, dict) else None
    factor = agent_number(phase.get("factor")) if isinstance(phase, dict) else None
    if factor is None:
        return 1
    return int(min(max(factor, 1), MAX_PROBE_FACTOR))


def _measured(prev_details: dict | None) -> tuple[float | None, dict | None, dict | None]:
    """(ts, values, baseline) of the last measured run in the previous details."""
    if not isinstance(prev_details, dict):
        return None, None, None
    ts = agent_number(prev_details.get("measured_ts"))
    values = prev_details.get("values")
    baseline = prev_details.get("baseline")
    return (
        ts,
        values if isinstance(values, dict) else None,
        baseline if isinstance(baseline, dict) else None,
    )


def _rule_holds(rule: dict, value: object, before: object, ts: float) -> bool | None:
    """Whether the rule's alerting case holds; None when the value cannot be rated."""
    op, want = rule.get("op"), rule.get("value")
    if value is None:
        return None
    if op == "eq":
        return _same(value, want)
    if op == "ne":
        return not _same(value, want)
    if op == "in":
        return isinstance(want, list) and any(_same(value, w) for w in want)
    number = agent_number(value)
    limit = agent_number(want)
    if number is None or limit is None:
        return None
    if op in _COMPARE:
        return _COMPARE[op](number, limit)
    if op == "max_age":
        # The value is a point in time (unix seconds) the agent read, e.g. a unit's start.
        return ts - number > limit
    if op == "delta_gt":
        # A counter that went down (a restart reset it) is no rise; without an earlier
        # run there is nothing to compare, which is not a problem either.
        start = agent_number(before)
        return start is not None and number - start > limit
    if op == "drop_pct_gt":
        # Against the run before only: the alert holds until the next run measures again.
        start = agent_number(before)
        return start is not None and start > 0 and (start - number) * 100 / start > limit
    return None


def _rule_text(rule: dict, value: object, before: object, ts: float, clears: object = None) -> str:
    field, op, want = rule.get("field"), rule.get("op"), rule.get("value")
    if op == "max_age":
        return f"{field} is {int(ts - value)} s old ({op} {_shown(want)})"
    if op == "delta_gt":
        return f"{field} rose by {value - before:g} ({op} {_shown(want)})"
    if op == "drop_pct_gt":
        return f"{field} fell by {(before - value) * 100 / before:.0f} % ({op} {_shown(want)})"
    if clears is not None:
        return f"{field} = {_shown(value)} ({op} {_shown(want)}, clears at {_shown(clears)})"
    return f"{field} = {_shown(value)} ({op} {_shown(want)})"


def _rule_key(rule: dict) -> str:
    # As catalog.model.rule_key, on the stored form of the rule.
    return rule.get("key") or f"{rule.get('field')}.{rule.get('level')}"


def _condition_holds(
    when: dict, values: dict, siblings: dict, report_ts: float, factor: int
) -> bool | None:
    """Whether a rule's condition holds; None when it cannot be told: no usable value, or a
    sibling without a result as fresh as its own probe would need (or `max_age`)."""
    check = when.get("check")
    source: object = values
    if check is not None:
        sibling = siblings.get(check)
        if not isinstance(sibling, dict):
            return None
        measured = agent_number(sibling.get("measured_ts"))
        limit = agent_number(when.get("max_age"))
        if limit is None:
            limit = _stale_after(sibling.get("interval_s"), factor)
        if measured is None or report_ts - measured > limit:
            return None
        source = sibling.get("values")
    if not isinstance(source, dict):
        return None
    condition = {"op": when.get("op"), "value": when.get("value")}
    return _rule_holds(condition, source.get(when.get("field")), None, report_ts)


class Rating(NamedTuple):
    status: str
    problems: list[str]
    # The keys of the rules that hold, for the hysteresis of the next run.
    firing: list[str]
    # The rules whose condition does not hold: {"key": …, "when": …}.
    resting: list[dict]


def _rating(
    rules: object,
    values: dict,
    baseline: dict | None,
    ts: float,
    *,
    firing: frozenset[str],
    siblings: object,
    report_ts: float,
    factor: int = 1,
) -> Rating:
    """The rules on a measured result. `firing`: the keys that held in the rated run before;
    `siblings`: the stored results of the module's other probe checks at this instance."""
    worst = 0
    held: list[str] = []
    unrated: list[str] = []
    now_firing: list[str] = []
    resting: list[dict] = []
    siblings = siblings if isinstance(siblings, dict) else {}
    for rule in rules if isinstance(rules, list) else []:
        if not isinstance(rule, dict):
            continue
        key = _rule_key(rule)
        field = rule.get("field")
        value = values.get(field)
        unless = rule.get("unless")
        if isinstance(unless, dict) and _same(values.get(unless.get("field")), unless.get("value")):
            continue
        when = rule.get("when")
        if isinstance(when, dict):
            # Only a condition that is told and fails rests the rule: missing or old data
            # never silences it.
            if _condition_holds(when, values, siblings, report_ts, factor) is False:
                resting.append({"key": key, "when": when})
                continue
        before = (baseline or {}).get(field)
        holds = _rule_holds(rule, value, before, ts)
        clears = rule.get("clear")
        holding = clears is not None and holds is False and key in firing
        if holding and _rule_holds({**rule, "value": clears}, value, before, ts):
            holds = True
        else:
            clears = None
        if holds is None and key in firing:
            # A gap does not end the hysteresis: the rule holds again once a value comes back
            # on the wrong side of clear.
            now_firing.append(key)
        if holds is None and rule.get("level") == "info":
            # A hint never makes a check worse than info: no value, no hint (OPNsense sends
            # update_available only after an update check).
            continue
        if value is None and rule.get("if_absent") == "ok":
            continue
        if holds is None:
            unrated.append(f"{field}: no usable value in the probe result")
        elif holds:
            now_firing.append(key)
            held.append(_rule_text(rule, value, before, ts, clears))
            worst = max(worst, _LEVELS.get(rule.get("level"), _LEVELS["critical"]))
    now_firing = list(dict.fromkeys(now_firing))
    # A held info rule must not hide a rule without a value: unknown ranks above info.
    if held and worst > _LEVELS["info"]:
        return Rating(_LEVEL_NAMES[worst], held, now_firing, resting)
    if unrated:
        return Rating("unknown", unrated, now_firing, resting)
    if held:
        return Rating("info", held, now_firing, resting)
    return Rating("ok", [], now_firing, resting)


def _rate(rules: object, values: dict, baseline: dict | None, ts: float) -> tuple[str, list[str]]:
    """(status, problems) of the rules on a measured result, without a run before and without
    siblings."""
    rating = _rating(rules, values, baseline, ts, firing=frozenset(), siblings={}, report_ts=ts)
    return rating.status, rating.problems


def _ok_text(values: dict) -> str:
    shown = [f"{field} = {_shown(value)}" for field, value in values.items()]
    return f"OK: {join_capped(shown)}" if shown else "Probe OK"


def _firing(prev_details: dict | None) -> list[str]:
    keys = prev_details.get("firing") if isinstance(prev_details, dict) else None
    return [k for k in keys if isinstance(k, str)] if isinstance(keys, list) else []


class ProbeChecker:
    """Rates the result of one probe the agent ran.

    Config: sensor, target, params, fields, rules, interval_s, timeout_s, credential,
    test_object, when (check_configs.ProbeConfig). The agent router adds `_check_id`, the
    key of the result in the report's probes block, and `_siblings`, the stored results of
    the module's other probe checks at the same instance that the check's or a rule's `when`
    names.
    """

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return "unknown", "Waiting for agent data", None

    def evaluate(
        self, config: dict, report: dict, prev_details: dict | None = None
    ) -> tuple[str, str, dict | None]:
        probes = report.get("probes")
        result = probes.get(config.get("_check_id")) if isinstance(probes, dict) else None
        if not isinstance(result, dict):
            # Nothing new to show: the stored details stay (no details returned).
            return "unknown", "No result for this probe in the agent report", None

        status = result.get("status")
        status = status if isinstance(status, str) else None
        ts = agent_number(result.get("ts"))
        error = cap_agent_text(result.get("error"))
        measured_ts, values, baseline = _measured(prev_details)
        firing = _firing(prev_details)
        details = {
            "ts": ts,
            "status": status,
            "error": error,
            "measured_ts": measured_ts,
            "values": values or {},
            "baseline": baseline,
            "problems": [],
            # A run without a rating keeps the hysteresis of the last rated one.
            "firing": firing,
            "resting": [],
        }

        def done(level: str, problems: list[str]) -> tuple[str, str, dict | None]:
            details["problems"] = problems
            return level, join_capped(problems, "; "), {"_details": details}

        if status in _NOT_RUN:
            level, text = _NOT_RUN[status]
            return done(level, [f"{text}: {error}" if error else text])
        if status not in ("ok", "error"):
            return done("unknown", [f"Unknown probe status {_shown(status)}"])

        if ts is None:
            return done("unknown", ["Probe result without a time"])
        factor = _probe_factor(report)
        now = _report_time(report)
        age = now - ts
        if age > _stale_after(config.get("interval_s"), factor):
            return done(
                "unknown",
                [f"Last probe result is {int(age // 60)} min old; the agent no longer runs it"],
            )

        siblings = config.get("_siblings")
        siblings = siblings if isinstance(siblings, dict) else {}
        when = config.get("when")
        # Before the error: in an AIO backup the target is stopped, the run fails, and the
        # check is to rest all the same (ADR 0004 §6.4). Only a condition that is told and
        # fails rests it: missing or old data never silences it.
        rests = (
            isinstance(when, dict) and _condition_holds(when, {}, siblings, now, factor) is False
        )
        failed = f"Probe failed: {error}" if error else "Probe failed"
        if status == "error" and not rests:
            return done("critical", [failed])

        if status == "ok":
            current = _values(result.get("values"), config.get("fields"))
            if measured_ts != ts:
                # A new run: the run before it becomes the baseline of delta rules. The same
                # run sent again keeps its baseline, else a delta would fall to 0 one report
                # later.
                baseline = values
            details.update(measured_ts=ts, values=current, baseline=baseline)
        if rests:
            rules = config.get("rules")
            details["resting"] = [
                {"key": _rule_key(rule), "when": when}
                for rule in (rules if isinstance(rules, list) else [])
                if isinstance(rule, dict)
            ]
            details["firing"] = []
            # Told and failed: the sibling and its value are there (_condition_holds).
            told = siblings[when["check"]]["values"][when["field"]]
            outcome = failed if status == "error" else _ok_text(current)
            reason = f"{when['check']}.{when['field']} = {_shown(told)}"
            return "ok", f"Resting ({reason}): {outcome}", {"_details": details}

        rating = _rating(
            config.get("rules"),
            current,
            baseline,
            ts,
            firing=frozenset(firing),
            siblings=siblings,
            report_ts=now,
            factor=factor,
        )
        details.update(firing=rating.firing, resting=rating.resting)
        if rating.status != "ok":
            return done(rating.status, rating.problems)
        return "ok", _ok_text(current), {"_details": details}
