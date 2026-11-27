# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The admin's changes to a catalog check's rules as a layer of their own (R-1638, ADR 0004
§6.2): per rule key the parts value, clear, level and enabled over the catalog's rules,
which stay as the catalog wrote them. A catalog update is a three-way merge of the old
catalog, the new one and these overrides.

The catalog here is a check's rules as `probe_config` dumps them. A probe check of a module
keeps its layer in monitor_checks.rule_layer, also one without rules; NULL means a check of
another kind or one whose rules the admin changed before the layer and stay theirs alone
(frozen). Nothing here reads the database.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from app.catalog.model import Rule, clear_fits, rule_key
from app.models import MonitorCheck
from app.template_sync import TEMPLATE_CHECK_FIELDS, read_overrides

# The parts a catalog rule sets and an override takes over.
_RULE_PARTS = ("value", "clear", "level")
# What the admin cannot change: another field or condition is another rule.
_FIXED = ("field", "op", "when", "unless", "if_absent")


def _same(a: object, b: object) -> bool:
    """Equal as JSON values: true is not 1, and 90 is 90.0 (as probe._same), also in a list
    or a condition."""
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(_same, a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    return a == b


def _by_key(catalog: list[dict]) -> dict[str, Rule]:
    rules = (Rule.model_validate(rule) for rule in catalog)
    return {rule_key(rule): rule for rule in rules}


def _part(rule: Rule, part: str) -> object:
    return True if part == "enabled" else getattr(rule, part)


def effective(catalog: list[dict], overrides: dict[str, dict]) -> list[dict]:
    """The rules a check rates with: the catalog's, in its order, each with the parts of its
    override; a rule switched off is left out. Raises ValueError when an override does not
    fit its rule (clear on the wrong side of the limit, a value the operator cannot take)."""
    rules = []
    for key, rule in _by_key(catalog).items():
        override = overrides.get(key, {})
        if override.get("enabled") is False:
            continue
        data = rule.model_dump()
        data.update({part: override[part] for part in _RULE_PARTS if part in override})
        if rule.key is None and data["level"] != rule.level:
            # The key is the rule's name in the overrides and the hysteresis; a new level
            # must not rename it.
            data["key"] = key
        rules.append(Rule.model_validate(data).model_dump())
    return rules


def normalize(catalog: list[dict], overrides: dict[str, dict]) -> dict[str, dict]:
    """The overrides without the parts that equal the catalog's, in the catalog's order; an
    empty override and one of a rule the catalog does not have are left out."""
    normal = {}
    for key, rule in _by_key(catalog).items():
        kept = {
            part: value
            for part, value in overrides.get(key, {}).items()
            if not _same(value, _part(rule, part))
        }
        if kept:
            normal[key] = kept
    return normal


def overrides_from(catalog: list[dict], rules: list[dict]) -> tuple[dict | None, str | None]:
    """(the overrides that make `rules` out of the catalog, None) or (None, why they cannot).

    A sent rule finds its catalog rule by its key, an unchanged one first, so that a rule
    whose level a client from before the layer changed cannot take the key of the catalog
    rule of that level. Such a rule, without a key of its own, then takes the one catalog
    rule of its field and operator still free. A catalog rule without a sent rule is
    switched off."""
    by_key = _by_key(catalog)
    matched: dict[str, Rule] = {}
    pending = [Rule.model_validate(rule) for rule in rules]
    for unchanged in (True, False):
        rest = []
        for rule in pending:
            key = rule_key(rule)
            own = by_key.get(key)
            if own is None or key in matched:
                fits = False
            elif unchanged:
                fits = _same(rule.model_dump(), own.model_dump())
            else:
                fits = rule.key is not None or own.op == rule.op
            if fits:
                matched[key] = rule
            else:
                rest.append(rule)
        pending = rest
    for rule in pending:
        key = rule_key(rule)
        if rule.key is not None:
            if key in by_key:
                return None, f"two rules are the catalog rule {key!r}"
            return None, f"the rule key {key!r} names no catalog rule"
        free = [
            key
            for key, own in by_key.items()
            if key not in matched and (own.field, own.op) == (rule.field, rule.op)
        ]
        if not free:
            return None, f"the rule on {rule.field!r} with op {rule.op!r} is no catalog rule"
        if len(free) > 1:
            return None, f"the rule on {rule.field!r} could be any of {', '.join(free)}"
        matched[free[0]] = rule
    overrides: dict[str, dict] = {}
    for key, own in by_key.items():
        rule = matched.get(key)
        if rule is None:
            overrides[key] = {"enabled": False}
            continue
        sent, kept = rule.model_dump(), own.model_dump()
        for fixed in _FIXED:
            if not _same(sent.get(fixed), kept.get(fixed)):
                return None, f"the rule {key!r} changes its {fixed}, which the catalog sets"
        overrides[key] = {part: getattr(rule, part) for part in _RULE_PARTS}
    return normalize(catalog, overrides), None


def merge(
    old: list[dict], new: list[dict], overrides: dict[str, dict]
) -> tuple[dict[str, dict], list[dict]]:
    """(the overrides over the new catalog, the conflicts) after a catalog update.

    A part the catalog left alone keeps the admin's value; one the catalog moved to the
    admin's value loses the override; one both changed keeps the admin's (both_changed). A
    rule the catalog removed takes its override with it (removed); a catalog level change of
    a rule without a key renames it, so its override ends the same way. A rule that now
    rates another field or with another operator loses the admin's limits and keeps level
    and switch (redefined). A clear that the merge leaves on the wrong side of the limit is
    dropped (clear_dropped). Each conflict is {key, kind, part}; the overrides are those
    of the old catalog's keys, as normalize leaves them."""
    old_rules, new_rules = _by_key(old), _by_key(new)
    merged: dict[str, dict] = {}
    conflicts: list[dict] = []
    for key, then in old_rules.items():
        if key not in overrides:
            continue
        override = dict(overrides[key])
        now = new_rules.get(key)
        if now is None:
            conflicts.append({"key": key, "kind": "removed", "part": None})
            continue
        if (then.field, then.op) != (now.field, now.op):
            override.pop("value", None)
            override.pop("clear", None)
            conflicts.append({"key": key, "kind": "redefined", "part": None})
        for part in _RULE_PARTS:
            if part not in override or _same(_part(then, part), _part(now, part)):
                continue
            # Moved to the admin's value, the part is the catalog's again: normalize drops it.
            if not _same(_part(now, part), override[part]):
                conflicts.append({"key": key, "kind": "both_changed", "part": part})
        rule = {**now.model_dump(), **{p: override[p] for p in _RULE_PARTS if p in override}}
        if rule.get("clear") is not None and not clear_fits(
            rule["op"], rule["value"], rule["clear"]
        ):
            override["clear"] = None
            conflicts.append({"key": key, "kind": "clear_dropped", "part": "clear"})
        merged[key] = override
    return normalize(new, merged), conflicts


def convert(catalog: list[dict], rules: list[dict]) -> tuple[dict | None, str | None]:
    """(the overrides that give exactly `rules` out of the catalog, None) or (None, why not):
    rules the admin changed before the layer. Exactly is in order and content; an explicit
    key where the stored rule goes by the derived one is the key a level change keeps.
    Then the check rates as before."""
    overrides, why = overrides_from(catalog, rules)
    if overrides is None:
        return None, why
    # overrides_from gives each stored rule a catalog rule of its own and switches off the
    # rest, so the two lists are as long.
    given = [
        rule if "key" in stored else {part: v for part, v in rule.items() if part != "key"}
        for rule, stored in zip(effective(catalog, overrides), rules, strict=True)
    ]
    if not _same(given, rules):
        return None, "the catalog with these overrides gives the rules in another order or form"
    return overrides, None


def read_layer(row: MonitorCheck) -> dict | None:
    """The check's layer, {"catalog", "overrides", "conflicts"}, or None: a check other
    than a module's probe check, a frozen one, or a column that does not hold a layer."""
    try:
        layer = json.loads(row.rule_layer) if row.rule_layer else None
    except (TypeError, ValueError):
        return None
    if not (
        isinstance(layer, dict)
        and isinstance(layer.get("catalog"), list)
        and isinstance(layer.get("overrides"), dict)
        and isinstance(layer.get("conflicts"), list)
    ):
        return None
    return layer


def store_layer(
    row: MonitorCheck,
    catalog: list[dict],
    overrides: dict[str, dict],
    conflicts: Sequence[dict] = (),
) -> None:
    """Give the check the layer and the rules it rates with. The mark "config" stands exactly
    while overrides do, so clients still see that the rules are the admin's. Raises
    ValueError like effective."""
    overrides = normalize(catalog, overrides)
    config = json.loads(row.config)
    config["rules"] = effective(catalog, overrides)
    row.config = json.dumps(config)
    row.rule_layer = json.dumps(
        {"catalog": catalog, "overrides": overrides, "conflicts": list(conflicts)}
    )
    fields = read_overrides(row)
    if overrides:
        fields.add("config")
    else:
        fields.discard("config")
    row.overridden_fields = json.dumps([f for f in TEMPLATE_CHECK_FIELDS if f in fields])
