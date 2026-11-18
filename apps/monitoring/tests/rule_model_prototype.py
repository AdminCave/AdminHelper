# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prototype of the rule model of the target model (R-1558, R-1515; ADR 0004).

Only tests use it; P1 replaces it with the real model. It shows that one rule form carries
what the target model asks for: a stable key per rule, the admin's overrides as a layer of
their own over the catalog, a three-way merge when the catalog changes, the operator `rises`
and hysteresis, the value-bound exception, and a condition over another check of the same
instance, both as a rule's `when` and as an exception's condition.

The operators of today's probe rules are not copied: they are rated by
`app.checkers.probe._rule_holds`, so the prototype cannot drift from them.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Literal

from app.checkers.agent import agent_number
from app.checkers.probe import _rule_holds, _same

Level = Literal["info", "warning", "critical"]
Status = Literal["ok", "info", "unknown", "warning", "critical"]

TODAY_OPS = ("eq", "ne", "in", "lt", "le", "gt", "ge", "max_age", "delta_gt", "drop_pct_gt")
OPS = (*TODAY_OPS, "rises")
COMPARE_OPS = ("lt", "le", "gt", "ge")
# A condition compares what a sibling reports now; it has no run before and no age of its own.
CONDITION_OPS = ("eq", "ne", "in", "lt", "le", "gt", "ge")
# unknown ranks above info and below warning, as in probe._rate: a held hint must not hide a
# rule that has no value.
RANK: dict[Status, int] = {"ok": 0, "info": 1, "unknown": 2, "warning": 3, "critical": 4}


@dataclass(frozen=True)
class Condition:
    """A value reported under the same instance: by the same check (check None) or another
    check of the instance, by its own result (object None) or by one object below it (a
    container of a compose project). `max_age`: older data counts as unknown."""

    field: str
    op: str
    value: object
    check: str | None = None
    object: str | None = None
    max_age: float | None = None


@dataclass(frozen=True)
class Rule:
    """One rule of a check. Without an explicit `key` it is `<field>.<level>`: unique in
    today's catalog (the field alone is not: checks rate one field at two levels), and a
    level the catalog changes makes a new rule."""

    field: str
    op: str
    value: object
    level: Level
    key: str | None = None
    # Hysteresis: while the rule fires it is rated against `clear` instead of `value`, so a
    # value around the limit does not flap.
    clear: float | None = None
    when: Condition | None = None
    if_absent: Literal["ok"] | None = None
    # Today's spelling of a `when` on the same result ({"field", "value"}: the rule rests
    # while the field has the value), kept as it is so the module's hash stays.
    unless: dict | None = None

    @property
    def id(self) -> str:
        return self.key or f"{self.field}.{self.level}"

    def dump(self) -> dict:
        """As the catalog hashes it: the new options only when set and a derived key not at
        all, so a module that uses none of them keeps its definition hash."""
        data: dict = {"field": self.field, "op": self.op, "value": self.value, "level": self.level}
        if self.key is not None:
            data["key"] = self.key
        if self.clear is not None:
            data["clear"] = self.clear
        if self.when is not None:
            data["when"] = {
                f.name: getattr(self.when, f.name)
                for f in fields(self.when)
                if getattr(self.when, f.name) is not None
            }
        if self.if_absent is not None:
            data["if_absent"] = self.if_absent
        if self.unless is not None:
            data["unless"] = self.unless
        return data

    @classmethod
    def from_catalog(cls, rule: dict) -> Rule:
        """Today's catalog rule (`app.catalog.model.Rule.model_dump(mode="json")`)."""
        return cls(
            field=rule["field"],
            op=rule["op"],
            value=rule["value"],
            level=rule["level"],
            if_absent=rule.get("if_absent"),
            unless=rule.get("unless"),
        )


def _clear_fits(rule: Rule) -> bool:
    """Whether the rule's clear lies on the good side of its limit: below it for gt/ge, above
    it for lt/le. Only a compare operator with a number has a side."""
    limit = agent_number(rule.value)
    if rule.clear is None or rule.op not in COMPARE_OPS or limit is None:
        return False
    return rule.clear < limit if rule.op in ("gt", "ge") else rule.clear > limit


def rule_problems(rules: list[Rule], checks: tuple[str, ...]) -> list[str]:
    """Why the rules of one check do not hold; `checks` are the keys of the checks of the
    module. A condition names a check key of the module, which the server resolves within the
    same instance only: another instance cannot be named."""
    problems: list[str] = []
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            problems.append(f"{rule.id}: key given twice")
        seen.add(rule.id)
        if rule.op not in OPS:
            problems.append(f"{rule.id}: unknown operator {rule.op}")
        if rule.clear is not None and not _clear_fits(rule):
            if rule.op not in COMPARE_OPS or agent_number(rule.value) is None:
                problems.append(f"{rule.id}: clear needs a compare operator with a number")
            else:
                problems.append(f"{rule.id}: clear must lie on the good side of the limit")
        if rule.when is not None:
            if rule.when.op not in CONDITION_OPS:
                problems.append(f"{rule.id}: condition operator {rule.when.op}")
            if rule.when.check is not None and rule.when.check not in checks:
                problems.append(f"{rule.id}: condition names unknown check {rule.when.check}")
    return problems


@dataclass(frozen=True)
class Reading:
    """What one check, or one object below it, reported: the values, when, and the values of
    the run before (for delta_gt, drop_pct_gt and rises)."""

    values: dict
    ts: float
    before: dict | None = None


def _sibling(cond: Condition, own: str, siblings: dict[str, Reading]) -> Reading | None:
    check = cond.check or own
    return siblings.get(f"{check}/{cond.object}" if cond.object else check)


def condition_holds(
    cond: Condition, own: str, reading: Reading, siblings: dict[str, Reading], now: float
) -> bool | None:
    """Whether the condition holds; None when it cannot be told (nothing reported, no value,
    or older than `max_age`). `own` is the key of the check the rule or exception sits on."""
    # The own check named by its key is the same reading as no check at all.
    target = (
        reading
        if cond.check in (None, own) and cond.object is None
        else _sibling(cond, own, siblings)
    )
    if target is None:
        return None
    if cond.max_age is not None and now - target.ts > cond.max_age:
        return None
    return _rule_holds(
        {"op": cond.op, "value": cond.value}, target.values.get(cond.field), None, now
    )


def rule_holds(rule: Rule, reading: Reading, firing: frozenset[str]) -> bool | None:
    """Whether the rule's alerting case holds; None when the value cannot be rated."""
    value = reading.values.get(rule.field)
    before = (reading.before or {}).get(rule.field)
    if rule.op == "rises":
        # Against the object's own value of the run before; a counter that went down (a
        # restart reset it) is no rise, and without a run before there is nothing to compare.
        number, start = agent_number(value), agent_number(before)
        if number is None:
            return None
        return start is not None and number > start
    limit = rule.clear if rule.clear is not None and rule.id in firing else rule.value
    return _rule_holds(
        {"field": rule.field, "op": rule.op, "value": limit}, value, before, reading.ts
    )


def rate(
    rules: list[Rule],
    reading: Reading,
    *,
    check: str = "",
    siblings: dict[str, Reading] | None = None,
    firing: frozenset[str] = frozenset(),
) -> tuple[Status, list[str]]:
    """(status, rule ids held or unrated) as probe._rate rates it, plus `when`, `rises` and
    hysteresis. `firing`: the rules that held in the run before. A `when` that cannot be told
    lets the rule apply: missing data never silences a rule."""
    worst: Status = "ok"
    held: list[str] = []
    unrated: list[str] = []
    for rule in rules:
        if rule.unless is not None and _same(
            reading.values.get(rule.unless["field"]), rule.unless["value"]
        ):
            continue
        if (
            rule.when is not None
            and condition_holds(rule.when, check, reading, siblings or {}, reading.ts) is False
        ):
            continue
        holds = rule_holds(rule, reading, firing)
        if holds is None and rule.level == "info":
            continue
        if reading.values.get(rule.field) is None and rule.if_absent == "ok":
            continue
        if holds is None:
            unrated.append(rule.id)
        elif holds:
            held.append(rule.id)
            if RANK[rule.level] > RANK[worst]:
                worst = rule.level
    if held and RANK[worst] > RANK["info"]:
        return worst, held
    if unrated:
        return "unknown", unrated
    if held:
        return "info", held
    return "ok", []


@dataclass(frozen=True)
class Override:
    """The admin's change to one catalog rule; None leaves the catalog's part."""

    value: object = None
    clear: float | None = None
    level: Level | None = None
    enabled: bool | None = None


def effective(rules: list[Rule], overrides: dict[str, Override]) -> list[Rule]:
    """The rules the check rates with: the catalog's, each with the admin's override over it.
    An override whose rule the catalog no longer has does nothing (merge drops it). The key
    is fixed first: an override of the level must not turn the rule into another one. A clear
    that the overridden limit moved past is dropped: the rule then rates against its limit
    and reports, instead of resting while the value is past it."""
    out: list[Rule] = []
    for rule in rules:
        o = overrides.get(rule.id)
        if o is None:
            out.append(rule)
        elif o.enabled is not False:
            changed = replace(
                rule,
                key=rule.id,
                value=rule.value if o.value is None else o.value,
                clear=rule.clear if o.clear is None else o.clear,
                level=o.level or rule.level,
            )
            if changed.clear is not None and not _clear_fits(changed):
                changed = replace(changed, clear=None)
            out.append(changed)
    return out


@dataclass(frozen=True)
class Conflict:
    """What a catalog update did to an override, for the admin to look at.
    both_changed: catalog and admin changed the same part, the admin's stays;
    removed: the catalog dropped the rule, the override went with it;
    redefined: the rule rates another field or with another operator now, so the admin's
    limits are dropped and the level and the switch stay;
    clear_dropped: the limit moved past the clear (the catalog's or the admin's), so the rule
    rates against its limit without one."""

    key: str
    kind: Literal["both_changed", "removed", "redefined", "clear_dropped"]
    part: str | None = None


def merge(
    old: list[Rule], new: list[Rule], overrides: dict[str, Override]
) -> tuple[dict[str, Override], list[Conflict]]:
    """Three-way merge of a catalog update: the catalog before, the catalog now and the
    admin's overrides. A part the catalog left alone keeps the admin's value; a part the
    catalog changed to the admin's value needs no override any more."""
    before = {r.id: r for r in old}
    now = {r.id: r for r in new}
    kept: dict[str, Override] = {}
    conflicts: list[Conflict] = []
    for key, o in overrides.items():
        theirs = now.get(key)
        if theirs is None:
            conflicts.append(Conflict(key, "removed"))
            continue
        base = before.get(key, theirs)
        if (theirs.field, theirs.op) != (base.field, base.op):
            o = replace(o, value=None, clear=None)
            conflicts.append(Conflict(key, "redefined"))
        for part in ("value", "clear", "level"):
            mine = getattr(o, part)
            if mine is None:
                continue
            if _same(getattr(theirs, part), mine):
                o = replace(o, **{part: None})
            elif not _same(getattr(theirs, part), getattr(base, part)):
                conflicts.append(Conflict(key, "both_changed", part))
        merged = replace(
            theirs,
            value=theirs.value if o.value is None else o.value,
            clear=theirs.clear if o.clear is None else o.clear,
        )
        if merged.clear is not None and not _clear_fits(merged):
            o = replace(o, clear=None)
            conflicts.append(Conflict(key, "clear_dropped"))
        if o != Override():
            kept[key] = o
    return kept, conflicts


@dataclass(frozen=True)
class Exception_:
    """An exception on one check of an instance (the scopes are the mockup's, exceptions.ts;
    here only what the rule model adds). `bound`: field → value it was taken for; it ends for
    good once a value differs (`ended_at`), even if the value comes back. `condition`: it is
    in force only while this holds; when that cannot be told it rests, so the object
    reports."""

    bound: dict | None = None
    condition: Condition | None = None
    ended_at: float | None = None


def exception_state(
    e: Exception_, check: str, reading: Reading, siblings: dict[str, Reading], now: float
) -> Literal["active", "resting", "ended"]:
    if e.ended_at is not None or (
        e.bound is not None and any(not _same(reading.values.get(f), v) for f, v in e.bound.items())
    ):
        return "ended"
    if e.condition is not None and not condition_holds(e.condition, check, reading, siblings, now):
        return "resting"
    return "active"


def after_run(
    e: Exception_, check: str, reading: Reading, siblings: dict[str, Reading], now: float
) -> Exception_:
    """The exception as stored after a run: a bound value that changed ends it, with the time."""
    if e.ended_at is None and exception_state(e, check, reading, siblings, now) == "ended":
        return replace(e, ended_at=now)
    return e
