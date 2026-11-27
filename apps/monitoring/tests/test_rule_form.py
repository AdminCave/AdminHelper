# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rule form of P1d (R-1638, ADR 0004 §6): a key per rule, the clear of a hysteresis and
a condition on the same or a sibling's result, checked when the catalog loads, and left out
of the dump while unset so that no module's definition hash moves."""

import copy

import pytest
from pydantic import ValidationError

from app.catalog import get_catalog, load_catalog
from app.catalog.model import Rule, clear_fits, rule_key, rule_problems
from app.check_configs import ProbeConfig, validate_check_config

from .test_catalog import _VALID

_STATUS = {"field": "status_code", "op": "ne", "value": 200, "level": "critical"}
_SLOW = {"field": "duration_ms", "op": "gt", "value": 500, "level": "warning"}


def _module(rules, *, sibling=None, **check):
    raw = copy.deepcopy(_VALID)
    first = raw["checks"][0]
    first["fields"] = ["status_code", "duration_ms", "data.database.status"]
    first["rules"] = rules
    first.update(check)
    if sibling is not None:
        raw["checks"][1].update(sibling)
    return raw


def _errors(raw):
    return load_catalog([("m", raw)]).errors


def _only_error(raw):
    errors = _errors(raw)
    assert len(errors) == 1, errors
    return errors[0]


class TestKey:
    def test_without_a_key_the_rule_is_named_by_field_and_level(self):
        assert rule_key(Rule(**_STATUS)) == "status_code.critical"

    def test_an_explicit_key_names_the_rule(self):
        assert rule_key(Rule(**_STATUS, key="reachable")) == "reachable"

    def test_a_key_with_a_dot_is_refused_so_it_never_meets_a_derived_one(self):
        with pytest.raises(ValidationError):
            Rule(**_STATUS, key="status_code.critical")

    def test_two_rules_with_one_derived_key_are_refused(self):
        twice = {**_STATUS, "value": 204}
        assert "rule key 'status_code.critical' is given twice" in _only_error(
            _module([_STATUS, twice])
        )

    def test_an_explicit_key_tells_two_rules_on_one_field_and_level_apart(self):
        twice = {**_STATUS, "op": "eq", "value": 500, "key": "server_error"}
        assert _errors(_module([_STATUS, twice])) == ()

    def test_an_explicit_key_given_twice_is_refused(self):
        rules = [{**_STATUS, "key": "a"}, {**_SLOW, "key": "a"}]
        assert rule_problems([Rule(**r) for r in rules]) == ["rule key 'a' is given twice"]

    def test_every_catalog_check_names_its_rules_apart(self):
        for module in get_catalog().modules.values():
            for check in module.checks:
                assert rule_problems(list(check.rules)) == [], (module.id, check.key)


class TestClear:
    @pytest.mark.parametrize(
        ("op", "value", "clear"),
        [("gt", 500, 400), ("ge", 90, 80.5), ("lt", 7, 14), ("le", 10.0, 20)],
    )
    def test_clear_on_the_good_side_of_the_limit_loads(self, op, value, clear):
        rule = {**_SLOW, "op": op, "value": value, "clear": clear}
        assert _errors(_module([rule])) == ()
        assert clear_fits(op, value, clear)

    @pytest.mark.parametrize(
        ("op", "value", "clear", "side"),
        [
            ("gt", 500, 500, "below"),
            ("gt", 500, 600, "below"),
            ("ge", 90, 90, "below"),
            ("lt", 7, 7, "above"),
            ("le", 10, 5, "above"),
        ],
    )
    def test_clear_on_or_past_the_limit_is_refused(self, op, value, clear, side):
        rule = {**_SLOW, "op": op, "value": value, "clear": clear}
        assert f"clear must lie {side} the limit" in _only_error(_module([rule]))
        assert not clear_fits(op, value, clear)

    @pytest.mark.parametrize(
        ("op", "value"), [("ne", 200), ("eq", 500), ("in", [500, 503]), ("delta_gt", 5)]
    )
    def test_clear_needs_a_compare_operator(self, op, value):
        rule = {**_STATUS, "op": op, "value": value, "clear": 100}
        assert "clear needs op lt, le, gt or ge" in _only_error(_module([rule]))

    @pytest.mark.parametrize("clear", ["400", True, float("nan")])
    def test_clear_is_a_number(self, clear):
        with pytest.raises(ValidationError):
            Rule(**_SLOW, clear=clear)


class TestWhen:
    def test_a_condition_on_the_own_result_loads(self):
        rule = {**_SLOW, "when": {"field": "status_code", "op": "eq", "value": 200}}
        assert _errors(_module([rule])) == ()

    def test_a_condition_on_a_field_the_check_does_not_ask_is_refused(self):
        rule = {**_SLOW, "when": {"field": "uptime_s", "op": "gt", "value": 60}}
        assert "when field 'uptime_s' is not among the check's fields" in _only_error(
            _module([rule])
        )

    @pytest.mark.parametrize(
        ("op", "value", "message"),
        [
            ("in", 200, "when: op 'in' needs a list"),
            ("in", [], "when: op 'in' needs a list"),
            ("eq", [200], "when: op 'eq' needs a single value"),
            ("gt", "ten", "when: op 'gt' needs a number"),
        ],
    )
    def test_the_condition_value_fits_its_operator(self, op, value, message):
        rule = {**_SLOW, "when": {"field": "status_code", "op": op, "value": value}}
        assert message in _only_error(_module([rule]))

    @pytest.mark.parametrize("op", ["max_age", "delta_gt", "drop_pct_gt", "rises"])
    def test_a_condition_compares_only_what_is_reported_now(self, op):
        with pytest.raises(ValidationError):
            Rule(**_SLOW, when={"field": "status_code", "op": op, "value": 1})

    def test_max_age_needs_a_check(self):
        rule = {**_SLOW, "when": {"field": "status_code", "op": "eq", "value": 1, "max_age": 60}}
        assert "when: max_age needs a check" in _only_error(_module([rule]))

    def test_a_condition_on_a_sibling_loads(self):
        when = {"field": "ok", "op": "eq", "value": True, "check": "test_mail", "max_age": 1800}
        assert _errors(_module([{**_SLOW, "when": when}])) == ()

    @pytest.mark.parametrize(
        ("check", "message"),
        [
            ("backup", "when.check 'backup' names no other check of the module"),
            ("status", "when.check 'status' names no other check of the module"),
        ],
    )
    def test_the_sibling_is_another_check_of_the_module(self, check, message):
        when = {"field": "ok", "op": "eq", "value": True, "check": check}
        assert message in _only_error(_module([{**_SLOW, "when": when}]))

    def test_the_sibling_reports_the_field(self):
        when = {"field": "status_code", "op": "eq", "value": 200, "check": "test_mail"}
        assert "when field 'status_code' is not among 'test_mail''s fields" in _only_error(
            _module([{**_SLOW, "when": when}])
        )

    def test_a_sibling_bound_at_one_instance_only_is_refused(self):
        when = {"field": "ok", "op": "eq", "value": True, "check": "test_mail"}
        raw = _module([{**_SLOW, "when": when}], sibling={"instance": "mail"})
        assert "'test_mail' is bound only at instance 'mail'" in _only_error(raw)

    def test_a_sibling_bound_at_the_same_instance_loads(self):
        when = {"field": "ok", "op": "eq", "value": True, "check": "test_mail"}
        raw = _module([{**_SLOW, "when": when}], sibling={"instance": "mail"}, instance="mail")
        assert _errors(raw) == ()

    @pytest.mark.parametrize("max_age", [0, 7 * 86400 + 1, "60"])
    def test_max_age_is_bounded(self, max_age):
        when = {"field": "ok", "op": "eq", "value": True, "check": "test_mail", "max_age": max_age}
        with pytest.raises(ValidationError):
            Rule(**_SLOW, when=when)


class TestDump:
    def test_unset_options_are_left_out_so_the_hash_stays(self):
        assert Rule(**_SLOW).model_dump() == _SLOW

    def test_set_options_are_written_and_the_condition_without_its_unset_parts(self):
        when = {"field": "status_code", "op": "in", "value": [200, 204]}
        rule = Rule(**_SLOW, key="slow", clear=400, when=when)
        assert rule.model_dump(mode="json") == {**_SLOW, "key": "slow", "clear": 400, "when": when}

    def test_a_dumped_rule_validates_back_to_itself(self):
        when = {"field": "ok", "op": "ne", "value": False, "check": "test_mail", "max_age": 600}
        rule = Rule(**_SLOW, key="slow", clear=400.5, when=when)
        assert Rule.model_validate(rule.model_dump(mode="json")) == rule


class TestProbeConfig:
    """A probe check stores its rules in its config; the new options pass the API boundary
    like the rest of the rule and are checked the same way."""

    def _config(self, rules):
        return {
            "sensor": "http",
            "target": {"kind": "container", "name": "app-web-1", "port_hint": 8000},
            "params": {"path": "/status"},
            "interval_s": 300,
            "fields": ["status_code", "duration_ms"],
            "rules": rules,
        }

    def test_key_clear_and_a_sibling_condition_are_kept(self):
        when = {"field": "ok", "op": "eq", "value": True, "check": "test_mail"}
        rules = [{**_SLOW, "key": "slow", "clear": 400, "when": when}]
        validate_check_config("probe", self._config(rules))
        config = ProbeConfig.model_validate(self._config(rules))
        assert [r.model_dump(mode="json") for r in config.rules] == rules

    @pytest.mark.parametrize(
        "rule",
        [
            {**_SLOW, "clear": 600},
            {**_STATUS, "clear": 100},
            {**_SLOW, "when": {"field": "uptime_s", "op": "gt", "value": 1}},
        ],
    )
    def test_a_broken_option_is_refused(self, rule):
        with pytest.raises(ValueError):
            validate_check_config("probe", self._config([rule]))

    def test_a_stored_config_with_two_rules_alike_stays_valid(self):
        # Stored before rule keys existed: the agent plan checks it again on every build and
        # leaves out what fails, so refusing it here would end its monitoring.
        rules = [_SLOW, {**_SLOW, "op": "lt", "value": 1}]
        validate_check_config("probe", self._config(rules))
        assert len(ProbeConfig.model_validate(self._config(rules)).rules) == 2
