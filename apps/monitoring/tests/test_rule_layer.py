# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The admin's rule layer over a catalog check (R-1638, ADR 0004 §6.2): the rules a check
rates with, the overrides a sent rule set makes, and the three-way merge of a catalog
update."""

import pytest

from app.catalog import get_catalog
from app.catalog.model import rule_problems
from app.rule_layer import effective, merge, normalize, overrides_from

_SLOW = {"field": "duration_ms", "op": "gt", "value": 500, "level": "warning", "clear": 400}
_VERY_SLOW = {"field": "duration_ms", "op": "gt", "value": 2000, "level": "critical"}
_DOWN = {"field": "status_code", "op": "ne", "value": 200, "level": "critical"}
_CATALOG = [_SLOW, _VERY_SLOW, _DOWN]
# A rule with a key of its own keeps it over a level change in the catalog.
_NAMED = {"field": "duration_ms", "op": "gt", "value": 500, "level": "warning", "key": "slow"}


def _catalog_rules():
    for module in get_catalog().modules.values():
        for check in module.checks:
            if check.rules:
                yield f"{module.id}/{check.key}", [rule.model_dump() for rule in check.rules]


class TestEffective:
    def test_without_overrides_the_rules_are_the_catalogs(self):
        assert effective(_CATALOG, {}) == _CATALOG

    def test_without_overrides_every_catalog_check_rates_as_its_probe_config_says(self):
        # probe_config writes [rule.model_dump() for rule in check.rules] (module_sync.py).
        checks = list(_catalog_rules())
        assert checks
        for name, rules in checks:
            assert effective(rules, {}) == rules, name

    def test_an_override_sets_its_parts_in_the_catalogs_order(self):
        rules = effective(_CATALOG, {"duration_ms.warning": {"value": 700, "clear": 600}})
        assert rules == [{**_SLOW, "value": 700, "clear": 600}, _VERY_SLOW, _DOWN]

    def test_a_rule_switched_off_is_left_out(self):
        overrides = {"duration_ms.critical": {"enabled": False}, "status_code.critical": {}}
        assert effective(_CATALOG, overrides) == [_SLOW, _DOWN]

    def test_clear_none_takes_the_catalogs_clear_away(self):
        rules = effective(_CATALOG, {"duration_ms.warning": {"clear": None}})
        assert rules[0] == {k: v for k, v in _SLOW.items() if k != "clear"}

    def test_a_level_change_keeps_the_rules_key(self):
        rules = effective(_CATALOG, {"duration_ms.warning": {"level": "critical"}})
        assert rules[0] == {**_SLOW, "level": "critical", "key": "duration_ms.warning"}
        # Without the key it would be a second duration_ms.critical.
        assert rule_problems_of(rules) == []

    def test_a_rule_with_a_key_of_its_own_needs_none_for_a_level_change(self):
        assert effective([_NAMED], {"slow": {"level": "critical"}}) == [
            {**_NAMED, "level": "critical"}
        ]

    @pytest.mark.parametrize(
        "override",
        [{"value": 300}, {"value": "fast"}, {"clear": 600}, {"level": "fatal"}],
    )
    def test_an_override_that_does_not_fit_its_rule_is_refused(self, override):
        with pytest.raises(ValueError):
            effective(_CATALOG, {"duration_ms.warning": override})


def rule_problems_of(rules):
    from app.catalog.model import Rule

    return rule_problems([Rule.model_validate(rule) for rule in rules])


class TestNormalize:
    def test_parts_like_the_catalogs_and_empty_overrides_are_left_out(self):
        overrides = {
            "status_code.critical": {"value": 200, "level": "critical", "enabled": True},
            "duration_ms.warning": {"value": 500.0, "clear": 400, "level": "info"},
            "duration_ms.critical": {},
        }
        assert normalize(_CATALOG, overrides) == {"duration_ms.warning": {"level": "info"}}

    def test_the_overrides_follow_the_catalogs_order(self):
        overrides = {"status_code.critical": {"value": 204}, "duration_ms.warning": {"value": 9}}
        assert list(normalize(_CATALOG, overrides)) == [
            "duration_ms.warning",
            "status_code.critical",
        ]

    def test_an_override_of_a_rule_the_catalog_does_not_have_is_left_out(self):
        assert normalize(_CATALOG, {"uptime_s.warning": {"value": 1}}) == {}

    def test_clear_none_stays_only_where_the_catalog_has_a_clear(self):
        overrides = {
            "duration_ms.warning": {"clear": None},
            "duration_ms.critical": {"clear": None},
        }
        assert normalize(_CATALOG, overrides) == {"duration_ms.warning": {"clear": None}}

    def test_true_is_not_one(self):
        catalog = [{"field": "ok", "op": "eq", "value": True, "level": "critical"}]
        assert normalize(catalog, {"ok.critical": {"value": 1}}) == {"ok.critical": {"value": 1}}


_ROUND_TRIPS = [
    {},
    {"duration_ms.warning": {"value": 700}},
    {"duration_ms.warning": {"clear": None}},
    {"duration_ms.warning": {"value": 900, "clear": 450}},
    {"duration_ms.warning": {"level": "critical"}},
    {"duration_ms.warning": {"level": "critical"}, "duration_ms.critical": {"level": "info"}},
    {"duration_ms.critical": {"enabled": False}, "status_code.critical": {"value": 204}},
    {key: {"enabled": False} for key in ("duration_ms.warning", "status_code.critical")},
]


class TestOverridesFrom:
    @pytest.mark.parametrize("overrides", _ROUND_TRIPS)
    def test_the_effective_rules_give_back_their_overrides(self, overrides):
        rules = effective(_CATALOG, overrides)
        assert overrides_from(_CATALOG, rules) == (normalize(_CATALOG, overrides), None)

    def test_every_catalog_check_gives_back_its_overrides(self):
        levels = ("info", "warning", "critical")
        for name, rules in _catalog_rules():
            first, *rest = [rule_key_of(rule) for rule in rules]
            overrides = {first: {"enabled": False}}
            for key, rule in zip(rest, rules[1:], strict=True):
                overrides[key] = {"level": levels[(levels.index(rule["level"]) + 1) % 3]}
            sent = effective(rules, overrides)
            assert overrides_from(rules, sent) == (normalize(rules, overrides), None), name

    def test_a_level_changed_by_a_client_from_before_the_layer_finds_its_rule(self):
        # An old client sends the rule without the frozen key, its level changed.
        sent = [{**_SLOW, "level": "info"}, _VERY_SLOW, _DOWN]
        assert overrides_from(_CATALOG, sent) == ({"duration_ms.warning": {"level": "info"}}, None)

    @pytest.mark.parametrize("order", [(0, 1, 2), (1, 0, 2), (2, 1, 0)])
    def test_a_level_raised_onto_another_rules_key_keeps_both_apart(self, order):
        # A disk pair: raising the warning to critical meets the critical rule's derived key.
        rules = [{**_SLOW, "level": "critical"}, _VERY_SLOW, _DOWN]
        sent = [rules[i] for i in order]
        assert overrides_from(_CATALOG, sent) == (
            {"duration_ms.warning": {"level": "critical"}},
            None,
        )

    def test_a_catalog_rule_left_out_is_switched_off(self):
        assert overrides_from(_CATALOG, [_SLOW, _DOWN]) == (
            {"duration_ms.critical": {"enabled": False}},
            None,
        )

    def test_a_clear_left_out_takes_the_catalogs_away(self):
        sent = [{**_SLOW, "clear": None}, _VERY_SLOW, _DOWN]
        assert overrides_from(_CATALOG, sent) == ({"duration_ms.warning": {"clear": None}}, None)

    @pytest.mark.parametrize(
        ("sent", "reason"),
        [
            ([*_CATALOG, {**_DOWN, "field": "uptime_s"}], "the rule on 'uptime_s' with op 'ne'"),
            ([*_CATALOG, _DOWN], "the rule on 'status_code' with op 'ne' is no catalog rule"),
            ([_SLOW, _VERY_SLOW, {**_DOWN, "op": "eq"}], "the rule on 'status_code' with op 'eq'"),
            ([{**_SLOW, "key": "slow"}], "the rule key 'slow' names no catalog rule"),
        ],
    )
    def test_a_rule_without_its_own_catalog_rule_is_not_expressible(self, sent, reason):
        overrides, why = overrides_from(_CATALOG, sent)
        assert overrides is None
        assert why.startswith(reason)

    def test_two_levels_changed_on_one_field_and_operator_are_not_expressible(self):
        # Which was the warning and which the critical rule, no part tells for sure.
        sent = [{**_SLOW, "level": "info"}, {**_VERY_SLOW, "level": "info"}, _DOWN]
        assert overrides_from(_CATALOG, sent) == (
            None,
            "the rule on 'duration_ms' could be any of duration_ms.warning, duration_ms.critical",
        )

    def test_two_rules_with_one_key_are_not_expressible(self):
        overrides, why = overrides_from([_NAMED], [_NAMED, {**_NAMED, "value": 900}])
        assert (overrides, why) == (None, "two rules are the catalog rule 'slow'")

    @pytest.mark.parametrize(
        ("change", "part"),
        [
            ({"op": "ge"}, "op"),
            ({"field": "uptime_s"}, "field"),
            ({"when": {"field": "status_code", "op": "eq", "value": 200}}, "when"),
            ({"unless": {"field": "status_code", "value": 503}}, "unless"),
            ({"if_absent": "ok"}, "if_absent"),
        ],
    )
    def test_a_part_the_catalog_sets_is_not_expressible(self, change, part):
        assert overrides_from([_NAMED], [{**_NAMED, **change}]) == (
            None,
            f"the rule 'slow' changes its {part}, which the catalog sets",
        )

    def test_a_condition_value_true_is_not_one(self):
        when = {"field": "ok", "op": "eq", "value": True}
        overrides, why = overrides_from(
            [{**_NAMED, "when": when}], [{**_NAMED, "when": {**when, "value": 1}}]
        )
        assert overrides is None
        assert why.endswith("changes its when, which the catalog sets")


def rule_key_of(rule):
    return rule.get("key") or f"{rule['field']}.{rule['level']}"


class TestMerge:
    def _merge(self, old, new, overrides):
        merged, conflicts = merge(old, new, overrides)
        effective(new, merged)  # the merge never leaves a rule that does not fit
        return merged, conflicts

    def test_without_overrides_nothing_is_kept(self):
        assert self._merge(_CATALOG, [{**_SLOW, "value": 600}], {}) == ({}, [])

    def test_a_part_the_catalog_left_alone_keeps_the_admins_value(self):
        new = [{**_SLOW, "clear": 300}, _VERY_SLOW, _DOWN]
        assert self._merge(_CATALOG, new, {"duration_ms.warning": {"value": 700}}) == (
            {"duration_ms.warning": {"value": 700}},
            [],
        )

    def test_a_part_the_catalog_moved_to_the_admins_value_loses_the_override(self):
        new = [{**_SLOW, "value": 700}, _VERY_SLOW, _DOWN]
        assert self._merge(_CATALOG, new, {"duration_ms.warning": {"value": 700}}) == ({}, [])

    @pytest.mark.parametrize(
        ("catalog", "admin", "part"),
        [
            ({"value": 600}, {"value": 700}, "value"),
            ({"clear": 300}, {"clear": 450}, "clear"),
            ({"clear": 300}, {"clear": None}, "clear"),
            ({"level": "info"}, {"level": "critical"}, "level"),
        ],
    )
    def test_a_part_both_changed_keeps_the_admins_value(self, catalog, admin, part):
        old = [{**_NAMED, "clear": 400}]
        new = [{**_NAMED, "clear": 400, **catalog}]
        assert self._merge(old, new, {"slow": admin}) == (
            {"slow": admin},
            [{"key": "slow", "kind": "both_changed", "part": part}],
        )

    def test_a_rule_the_catalog_removed_takes_its_override(self):
        overrides = {
            "duration_ms.critical": {"enabled": False},
            "status_code.critical": {"value": 204},
        }
        assert self._merge(_CATALOG, [_SLOW, _DOWN], overrides) == (
            {"status_code.critical": {"value": 204}},
            [{"key": "duration_ms.critical", "kind": "removed", "part": None}],
        )

    def test_a_catalog_level_change_of_a_rule_without_a_key_ends_its_override(self):
        new = [{**_SLOW, "level": "info"}, _VERY_SLOW, _DOWN]
        merged, conflicts = self._merge(_CATALOG, new, {"duration_ms.warning": {"value": 700}})
        assert (merged, conflicts) == (
            {},
            [{"key": "duration_ms.warning", "kind": "removed", "part": None}],
        )
        assert effective(new, merged) == new

    @pytest.mark.parametrize("change", [{"op": "ge"}, {"field": "elapsed_ms"}])
    def test_a_rule_that_rates_otherwise_keeps_only_level_and_switch(self, change):
        overrides = {"slow": {"value": 700, "clear": 600, "level": "critical", "enabled": False}}
        old = [{**_NAMED, "clear": 400}]
        assert self._merge(old, [{**_NAMED, **change}], overrides) == (
            {"slow": {"level": "critical", "enabled": False}},
            [{"key": "slow", "kind": "redefined", "part": None}],
        )

    def test_a_clear_the_catalog_adds_beyond_the_admins_limit_is_dropped(self):
        old = [{k: v for k, v in _SLOW.items() if k != "clear"}]
        merged, conflicts = self._merge(old, [_SLOW], {"duration_ms.warning": {"value": 300}})
        assert (merged, conflicts) == (
            {"duration_ms.warning": {"value": 300, "clear": None}},
            [{"key": "duration_ms.warning", "kind": "clear_dropped", "part": "clear"}],
        )
        assert "clear" not in effective([_SLOW], merged)[0]

    def test_the_admins_clear_beyond_a_moved_limit_is_dropped(self):
        new = [{**_SLOW, "value": 420}]
        merged, conflicts = self._merge([_SLOW], new, {"duration_ms.warning": {"clear": 450}})
        assert (merged, conflicts) == (
            {"duration_ms.warning": {"clear": None}},
            [{"key": "duration_ms.warning", "kind": "clear_dropped", "part": "clear"}],
        )

    def test_a_rule_switched_off_stays_off_over_an_update(self):
        new = [{**_SLOW, "value": 600}, _VERY_SLOW, _DOWN]
        overrides = {"duration_ms.warning": {"enabled": False}}
        assert self._merge(_CATALOG, new, overrides) == (overrides, [])

    def test_a_new_catalog_rule_comes_without_an_override(self):
        new = [*_CATALOG, {**_DOWN, "field": "uptime_s", "op": "lt", "value": 60}]
        merged, conflicts = self._merge(_CATALOG, new, {"duration_ms.warning": {"value": 700}})
        assert (merged, conflicts) == ({"duration_ms.warning": {"value": 700}}, [])
        assert effective(new, merged)[-1] == new[-1]
