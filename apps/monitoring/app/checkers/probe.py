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
rule describes the alerting case; the worst level that holds wins.
"""

from __future__ import annotations

import json
import operator
import time
from datetime import datetime

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
_LEVELS = {"warning": 1, "critical": 2}
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


def _rule_text(rule: dict, value: object, before: object, ts: float) -> str:
    field, op, want = rule.get("field"), rule.get("op"), rule.get("value")
    if op == "max_age":
        return f"{field} is {int(ts - value)} s old ({op} {_shown(want)})"
    if op == "delta_gt":
        return f"{field} rose by {value - before:g} ({op} {_shown(want)})"
    if op == "drop_pct_gt":
        return f"{field} fell by {(before - value) * 100 / before:.0f} % ({op} {_shown(want)})"
    return f"{field} = {_shown(value)} ({op} {_shown(want)})"


def _rate(rules: object, values: dict, baseline: dict | None, ts: float) -> tuple[str, list[str]]:
    """(status, problems) of the rules on a measured result."""
    worst = 0
    held: list[str] = []
    unrated: list[str] = []
    for rule in rules if isinstance(rules, list) else []:
        if not isinstance(rule, dict):
            continue
        field = rule.get("field")
        value = values.get(field)
        before = (baseline or {}).get(field)
        holds = _rule_holds(rule, value, before, ts)
        if holds is None:
            unrated.append(f"{field}: no usable value in the probe result")
        elif holds:
            held.append(_rule_text(rule, value, before, ts))
            worst = max(worst, _LEVELS.get(rule.get("level"), _LEVELS["critical"]))
    if held:
        return ("critical" if worst == _LEVELS["critical"] else "warning"), held
    if unrated:
        return "unknown", unrated
    return "ok", []


class ProbeChecker:
    """Rates the result of one probe the agent ran.

    Config: sensor, target, params, fields, rules, interval_s, timeout_s, credential,
    test_object (check_configs.ProbeConfig). The agent router adds `_check_id`, the key
    of the result in the report's probes block.
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
        details = {
            "ts": ts,
            "status": status,
            "error": error,
            "measured_ts": measured_ts,
            "values": values or {},
            "baseline": baseline,
            "problems": [],
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
        interval = agent_number(config.get("interval_s")) or DEFAULT_INTERVAL_S
        interval *= _probe_factor(report)
        age = _report_time(report) - ts
        if age > 2 * interval + AGENT_RUN_S:
            return done(
                "unknown",
                [f"Last probe result is {int(age // 60)} min old; the agent no longer runs it"],
            )

        if status == "error":
            return done("critical", [f"Probe failed: {error}" if error else "Probe failed"])

        current = _values(result.get("values"), config.get("fields"))
        if measured_ts != ts:
            # A new run: the run before it becomes the baseline of delta rules. The same
            # run sent again keeps its baseline, else a delta would fall to 0 one report later.
            baseline = values
        details.update(measured_ts=ts, values=current, baseline=baseline)
        level, problems = _rate(config.get("rules"), current, baseline, ts)
        if level != "ok":
            return done(level, problems)
        shown = [f"{field} = {_shown(value)}" for field, value in current.items()]
        details["problems"] = []
        message = f"OK: {join_capped(shown)}" if shown else "Probe OK"
        return "ok", message, {"_details": details}
