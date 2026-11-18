# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rule model prototype (R-1558, R-1515; ADR 0004): one test per property it claims,
the real catalog rated both ways, and today's catalog update that overwrites the admin's
rule as a merge scenario."""

import json
from dataclasses import fields
from datetime import UTC, datetime
from typing import get_args

import pytest

from app import module_sync
from app.catalog.loader import get_catalog, load_catalog
from app.catalog.model import Rule as CatalogRule
from app.checkers.agent import agent_number
from app.checkers.probe import _rate
from app.models import MonitorCheck

from .rule_model_prototype import (
    OPS,
    TODAY_OPS,
    Condition,
    Conflict,
    Exception_,
    Override,
    Reading,
    Rule,
    after_run,
    effective,
    exception_state,
    merge,
    rate,
    rule_problems,
)

TS = datetime(2026, 11, 18, 9, 0, tzinfo=UTC).timestamp()

WARN = Rule(field="used_pct", op="gt", value=80, level="warning")
CRIT = Rule(field="used_pct", op="gt", value=90, level="critical")


def _catalog_checks():
    for module in get_catalog().modules.values():
        for check in module.checks:
            yield module, check


# --- The catalog as it is ------------------------------------------------------------------


def test_every_catalog_rule_dumps_as_the_catalog_hashes_it():
    rules = 0
    for _, check in _catalog_checks():
        data = check.model_dump(mode="json")
        mine = [Rule.from_catalog(r).dump() for r in data["rules"]]
        assert mine == data["rules"], check.key
        rules += len(mine)
    # The prototype's form adds nothing to a rule that uses no new option, so no module's
    # definition hash changes and no check is offered an update for it.
    assert rules > 500


def test_derived_keys_are_unique_in_every_catalog_check_and_the_field_alone_is_not():
    doubled = []
    for module, check in _catalog_checks():
        rules = [Rule.from_catalog(r.model_dump(mode="json")) for r in check.rules]
        assert rule_problems(rules, tuple(c.key for c in module.checks)) == [], (
            module.id,
            check.key,
        )
        names = [r.field for r in rules]
        if len(names) != len(set(names)):
            doubled.append((module.id, check.key))
    # A key from the field alone would collide: many checks warn and alert on one field.
    assert len(doubled) > 10


def _candidates(field: str, rules: list[dict]) -> list[object]:
    """Values worth rating a field with: each rule's limit, around it and past it in time,
    the members of an `in` list, the value an `unless` names, text, and nothing."""
    out: list[object] = []
    for rule in rules:
        if rule["field"] == field:
            want = rule["value"]
            out.extend(want if isinstance(want, list) else [want])
            number = agent_number(want)
            if number is not None:
                out.extend([number - 1, number + 1])
                if rule["op"] == "max_age":
                    out.extend([TS - number - 1, TS - number + 1])
        unless = rule.get("unless")
        if unless and unless["field"] == field:
            out.append(unless["value"])
    out.extend(["text", None])
    seen: list[object] = []
    for value in out:
        if not any(type(value) is type(v) and value == v for v in seen):
            seen.append(value)
    return seen


def test_the_prototype_rates_every_catalog_check_as_the_probe_does():
    rated = 0
    for _, check in _catalog_checks():
        dumped = [r.model_dump(mode="json") for r in check.rules]
        if not dumped:
            continue
        rules = [Rule.from_catalog(r) for r in dumped]
        names = sorted(
            {r["field"] for r in dumped} | {r["unless"]["field"] for r in dumped if r.get("unless")}
        )
        candidates = {name: _candidates(name, dumped) for name in names}
        base = {name: candidates[name][0] for name in names}
        for name in names:
            for value in candidates[name]:
                values = {**base, name: value}
                for before in (None, base):
                    want = _rate(dumped, values, before, TS)[0]
                    got = rate(rules, Reading(values, TS, before))[0]
                    assert got == want, (check.key, values, before)
                    rated += 1
    assert rated > 1000


# --- Keys and overrides --------------------------------------------------------------------


def test_a_rule_without_a_key_is_its_field_and_level_and_a_given_key_wins():
    assert (WARN.id, CRIT.id) == ("used_pct.warning", "used_pct.critical")
    assert Rule(field="used_pct", op="gt", value=80, level="warning", key="space").id == "space"
    assert "key" not in WARN.dump()


def test_an_override_changes_its_rule_only():
    rules = effective([WARN, CRIT], {"used_pct.critical": Override(value=95)})

    assert [r.value for r in rules] == [80, 95]
    assert rate(rules, Reading({"used_pct": 93}, TS)) == ("warning", ["used_pct.warning"])
    assert rate(rules, Reading({"used_pct": 96}, TS))[0] == "critical"


def test_an_override_of_the_level_keeps_the_rule_it_belongs_to():
    rules = effective([WARN, CRIT], {"used_pct.critical": Override(level="warning")})

    status, held = rate(rules, Reading({"used_pct": 95}, TS))

    assert status == "warning"
    assert held == ["used_pct.warning", "used_pct.critical"]


def test_a_switched_off_rule_does_not_rate():
    rules = effective([WARN, CRIT], {"used_pct.critical": Override(enabled=False)})

    assert rate(rules, Reading({"used_pct": 95}, TS)) == ("warning", ["used_pct.warning"])


# --- Three-way merge -----------------------------------------------------------------------


def test_a_part_the_catalog_left_alone_keeps_the_admins_value():
    new = [WARN, CRIT, Rule(field="errors", op="gt", value=0, level="warning")]

    assert merge([WARN, CRIT], new, {"used_pct.critical": Override(value=95)}) == (
        {"used_pct.critical": Override(value=95)},
        [],
    )


def test_when_both_changed_a_part_the_admins_value_stays_and_it_is_named():
    new = [WARN, Rule(field="used_pct", op="gt", value=92, level="critical")]

    assert merge([WARN, CRIT], new, {"used_pct.critical": Override(value=95)}) == (
        {"used_pct.critical": Override(value=95)},
        [Conflict("used_pct.critical", "both_changed", "value")],
    )


def test_an_override_the_catalog_caught_up_with_goes_without_a_word():
    new = [WARN, Rule(field="used_pct", op="gt", value=95, level="critical")]
    overrides = {"used_pct.critical": Override(value=95, enabled=False)}

    assert merge([WARN, CRIT], new, overrides) == (
        {"used_pct.critical": Override(enabled=False)},
        [],
    )
    assert merge([WARN, CRIT], new, {"used_pct.critical": Override(value=95)}) == ({}, [])


def test_a_removed_rule_takes_its_override_along():
    assert merge([WARN, CRIT], [WARN], {"used_pct.critical": Override(value=95)}) == (
        {},
        [Conflict("used_pct.critical", "removed")],
    )


def test_a_redefined_rule_drops_the_admins_limits_and_keeps_level_and_switch():
    new = [WARN, Rule(field="used_pct", op="ge", value=90, level="critical")]
    overrides = {"used_pct.critical": Override(value=95, clear=85, level="warning")}

    assert merge([WARN, CRIT], new, overrides) == (
        {"used_pct.critical": Override(level="warning")},
        [Conflict("used_pct.critical", "redefined")],
    )


def test_a_new_rule_rates_with_the_catalogs_values():
    errors = Rule(field="errors", op="gt", value=0, level="warning")
    overrides, _ = merge([WARN, CRIT], [WARN, CRIT, errors], {})

    assert effective([WARN, CRIT, errors], overrides)[2] == errors


def test_a_level_the_catalog_changes_makes_a_new_rule_unless_it_has_a_key():
    # Without a key the override ends as a named conflict and the catalog's values rate:
    # the change errs towards reporting. A rule the catalog wants to move between levels
    # gets a key.
    raised = Rule(field="used_pct", op="gt", value=90, level="warning")
    assert merge([WARN, CRIT], [WARN, raised], {"used_pct.critical": Override(value=95)}) == (
        {},
        [Conflict("used_pct.critical", "removed")],
    )

    old = Rule(field="used_pct", op="gt", value=90, level="critical", key="full")
    new = Rule(field="used_pct", op="gt", value=90, level="warning", key="full")
    assert merge([old], [new], {"full": Override(value=95)}) == ({"full": Override(value=95)}, [])


def _backupjob(*rules: dict):
    return load_catalog(
        [
            (
                "backupjob",
                {
                    "id": "backupjob",
                    "name": "Backup job",
                    "version": 1,
                    "instance": "unit",
                    "detect": {"units": ["backupjob"]},
                    "checks": [
                        {
                            "key": "run",
                            "name": "Last run",
                            "sensor": "unit",
                            "target": {"kind": "unit"},
                            "interval": 300,
                            "fields": ["last_run_age_s", "restarts"],
                            "rules": list(rules),
                        }
                    ],
                },
            )
        ]
    )


def test_today_a_catalog_update_overwrites_the_admins_rule_and_the_merge_keeps_it():
    warn = {"field": "last_run_age_s", "op": "gt", "value": 93600, "level": "warning"}
    crit = {"field": "last_run_age_s", "op": "gt", "value": 172800, "level": "critical"}
    restarts = {"field": "restarts", "op": "delta_gt", "value": 0, "level": "warning"}
    before, after = _backupjob(warn, crit), _backupjob(warn, crit, restarts)
    assert (before.errors, after.errors) == ((), ())
    module, new_module = before.modules["backupjob"], after.modules["backupjob"]
    check, new_check = module.checks[0], new_module.checks[0]
    summary = {"unit": "backupjob.service"}
    config, reason = module_sync.probe_config(module, check, "backupjob.service", summary, [])
    assert reason is None
    # The job runs on weekends only: the admin raised the critical limit to three days in
    # the check's rules (routers/checks.py).
    config["rules"][1]["value"] = 259200
    row = MonitorCheck(check_type="probe", config=json.dumps(config))

    assert module_sync._update(row, new_module, new_check, "backupjob.service", summary, []) is None

    # Today: the update writes the catalog's rules over the admin's, the three days are gone.
    assert [r["value"] for r in json.loads(row.config)["rules"]] == [93600, 172800, 0]

    # Target model: the admin's change is an override of its own and survives the merge;
    # the catalog's definition, and so its hash, holds no override.
    old = [Rule.from_catalog(r.model_dump(mode="json")) for r in check.rules]
    new = [Rule.from_catalog(r.model_dump(mode="json")) for r in new_check.rules]
    mine = {"last_run_age_s.critical": Override(value=259200)}
    overrides, conflicts = merge(old, new, mine)
    assert (overrides, conflicts) == (mine, [])
    assert [r.value for r in effective(new, overrides)] == [93600, 259200, 0]
    assert [r.dump() for r in new] == [warn, crit, restarts]
    assert row.module_check_hash == module_sync.definition_hash(new_check)


# --- Operators: rises and hysteresis -------------------------------------------------------

RESTARTS = Rule(field="restart_count", op="rises", value=None, level="warning")


@pytest.mark.parametrize(
    ("value", "before", "status"),
    [
        pytest.param(3, 2, "warning", id="rose"),
        pytest.param(3, 3, "ok", id="same"),
        pytest.param(0, 5, "ok", id="counter-reset"),
        pytest.param(3, None, "ok", id="no-run-before"),
        pytest.param(None, 2, "unknown", id="no-value"),
        pytest.param(True, False, "unknown", id="bool-is-no-number"),
    ],
)
def test_rises_compares_with_the_objects_run_before(value, before, status):
    reading = Reading({"restart_count": value}, TS, {"restart_count": before})

    assert rate([RESTARTS], reading)[0] == status


def _run(rules: list[Rule], series: list[float]) -> list[str]:
    firing: frozenset[str] = frozenset()
    out = []
    for value in series:
        status, held = rate(rules, Reading({"used_pct": value}, TS), firing=firing)
        out.append(status)
        firing = frozenset(held) if status in ("warning", "critical") else frozenset()
    return out


def test_hysteresis_holds_a_firing_rule_until_the_clear_value():
    series = [91, 88, 86, 85, 88, 91]
    held = Rule(field="used_pct", op="gt", value=90, level="critical", clear=85)

    assert _run([CRIT], series) == ["critical", "ok", "ok", "ok", "ok", "critical"]
    assert _run([held], series) == ["critical", "critical", "critical", "ok", "ok", "critical"]


def test_hysteresis_for_a_lower_limit():
    low = Rule(field="free_pct", op="lt", value=10, level="warning", clear=15)
    firing = frozenset({low.id})

    assert rate([low], Reading({"free_pct": 12}, TS), firing=firing)[0] == "warning"
    assert rate([low], Reading({"free_pct": 16}, TS), firing=firing)[0] == "ok"
    assert rate([low], Reading({"free_pct": 12}, TS))[0] == "ok"


HELD = Rule(field="used_pct", op="gt", value=90, level="critical", clear=85)


def test_an_override_that_moves_the_limit_past_the_clear_drops_the_clear():
    (rule,) = effective([HELD], {"used_pct.critical": Override(value=80)})
    firing = frozenset({rule.id})

    assert (rule.value, rule.clear) == (80, None)
    assert rule_problems([rule], ("use",)) == []
    assert rate([rule], Reading({"used_pct": 83}, TS), firing=firing)[0] == "critical"


def test_a_catalog_limit_moved_past_the_admins_clear_drops_it_and_names_it():
    new = [Rule(field="used_pct", op="gt", value=80, level="critical")]
    overrides, conflicts = merge([CRIT], new, {"used_pct.critical": Override(clear=85)})
    (rule,) = effective(new, overrides)

    assert (overrides, conflicts) == ({}, [Conflict("used_pct.critical", "clear_dropped")])
    assert rate([rule], Reading({"used_pct": 83}, TS), firing=frozenset({rule.id}))[0] == (
        "critical"
    )
    # A clear still on the good side stays, without a word.
    assert merge([HELD], [HELD], {"used_pct.critical": Override(clear=80)}) == (
        {"used_pct.critical": Override(clear=80)},
        [],
    )


@pytest.mark.parametrize(
    ("rule", "problem"),
    [
        pytest.param(
            Rule(field="used_pct", op="gt", value=90, level="critical", clear=95),
            "used_pct.critical: clear must lie on the good side of the limit",
            id="gt-clear-above",
        ),
        pytest.param(
            Rule(field="free_pct", op="lt", value=10, level="warning", clear=5),
            "free_pct.warning: clear must lie on the good side of the limit",
            id="lt-clear-below",
        ),
        pytest.param(
            Rule(field="state", op="eq", value="failed", level="critical", clear=1),
            "state.critical: clear needs a compare operator with a number",
            id="eq-has-no-clear",
        ),
        pytest.param(
            Rule(field="used_pct", op="above", value=90, level="critical"),
            "used_pct.critical: unknown operator above",
            id="unknown-operator",
        ),
    ],
)
def test_rules_that_do_not_hold(rule, problem):
    assert rule_problems([rule], ("use",)) == [problem]


def test_two_rules_with_one_key_do_not_hold():
    assert rule_problems([WARN, WARN], ("use",)) == ["used_pct.warning: key given twice"]


def test_the_operators_are_todays_and_rises():
    assert set(get_args(CatalogRule.model_fields["op"].annotation)) == set(TODAY_OPS)
    assert set(OPS) - set(TODAY_OPS) == {"rises"}


# --- Value-bound exception -----------------------------------------------------------------


def test_a_value_bound_exception_ends_for_good_once_the_value_changes():
    e = Exception_(bound={"reallocated": 8})
    same, worse = Reading({"reallocated": 8}, TS), Reading({"reallocated": 9}, TS + 300)

    assert exception_state(e, "smart", same, {}, TS) == "active"
    e = after_run(e, "smart", same, {}, TS)
    assert e.ended_at is None

    e = after_run(e, "smart", worse, {}, TS + 300)
    assert e.ended_at == TS + 300
    # Back to the value it was taken for: still ended, the admin decides again.
    assert exception_state(e, "smart", same, {}, TS + 600) == "ended"


def test_a_value_bound_exception_ends_when_the_value_is_gone():
    e = Exception_(bound={"reallocated": 8})

    assert exception_state(e, "smart", Reading({}, TS), {}, TS) == "ended"


# --- Condition over another check of the same instance (R-1515) ----------------------------

# Nextcloud AIO: status.php reports maintenance while the nightly backup runs; the backup is
# a container of the same compose project, rated by the instance's container check.
MAINTENANCE = Rule(
    field="maintenance",
    op="eq",
    value=True,
    level="critical",
    when=Condition(
        check="containers",
        object="nextcloud-aio-borgbackup",
        field="state",
        op="ne",
        value="running",
        max_age=600,
    ),
)
IN_MAINTENANCE = Reading({"maintenance": True}, TS)


def _backup(state: str | None, age: float = 60) -> dict[str, Reading]:
    values = {} if state is None else {"state": state}
    return {"containers/nextcloud-aio-borgbackup": Reading(values, TS - age)}


@pytest.mark.parametrize(
    ("siblings", "status"),
    [
        pytest.param(_backup("running"), "ok", id="backup-runs"),
        pytest.param(_backup("exited"), "critical", id="no-backup"),
        pytest.param({}, "critical", id="backup-never-reported"),
        pytest.param(_backup(None), "critical", id="backup-without-state"),
        pytest.param(_backup("running", age=900), "critical", id="backup-data-stale"),
    ],
)
def test_a_rule_with_a_condition_applies_unless_the_condition_is_known_false(siblings, status):
    assert rate([MAINTENANCE], IN_MAINTENANCE, check="status", siblings=siblings)[0] == status


@pytest.mark.parametrize(
    ("siblings", "state"),
    [
        pytest.param(_backup("running"), "active", id="backup-runs"),
        pytest.param(_backup("exited"), "resting", id="no-backup"),
        pytest.param({}, "resting", id="backup-never-reported"),
        pytest.param(_backup("running", age=900), "resting", id="backup-data-stale"),
    ],
)
def test_an_exception_with_a_condition_rests_unless_the_condition_is_known_true(siblings, state):
    e = Exception_(
        condition=Condition(
            check="containers",
            object="nextcloud-aio-borgbackup",
            field="state",
            op="eq",
            value="running",
            max_age=600,
        )
    )

    assert exception_state(e, "status", IN_MAINTENANCE, siblings, TS) == state


def test_a_condition_on_a_whole_check_of_the_instance():
    rule = Rule(
        field="maintenance",
        op="eq",
        value=True,
        level="critical",
        when=Condition(check="backup", field="active", op="eq", value=False),
    )
    running = {"backup": Reading({"active": True}, TS)}

    assert rate([rule], IN_MAINTENANCE, check="status", siblings=running)[0] == "ok"


def test_a_condition_naming_its_own_check_reads_the_own_result():
    def rule(check):
        return Rule(
            field="maintenance",
            op="eq",
            value=True,
            level="critical",
            when=Condition(check=check, field="backup_running", op="ne", value=True),
        )

    for running in (True, False, None):
        reading = Reading({"maintenance": True, "backup_running": running}, TS)
        assert rate([rule("status")], reading, check="status") == rate(
            [rule(None)], reading, check="status"
        ), running


def test_a_condition_on_the_own_result_is_todays_unless():
    unless = Rule(
        field="realtime_on",
        op="eq",
        value=False,
        level="critical",
        unless={"field": "passive", "value": True},
    )
    when = Rule(
        field="realtime_on",
        op="eq",
        value=False,
        level="critical",
        when=Condition(field="passive", op="ne", value=True),
    )
    for realtime in (True, False, None):
        for passive in (True, False, None, "text"):
            reading = Reading({"realtime_on": realtime, "passive": passive}, TS)
            assert rate([unless], reading)[0] == rate([when], reading)[0], (realtime, passive)


def test_a_condition_names_a_check_of_the_module_and_no_instance():
    rule = Rule(
        field="maintenance",
        op="eq",
        value=True,
        level="critical",
        when=Condition(check="backup", field="active", op="delta_gt", value=0),
    )

    assert rule_problems([rule], ("status", "containers")) == [
        "maintenance.critical: condition operator delta_gt",
        "maintenance.critical: condition names unknown check backup",
    ]
    # The instance is the one the rule's check is bound to: a condition has no way to name
    # another one.
    assert {f.name for f in fields(Condition)} == {
        "field",
        "op",
        "value",
        "check",
        "object",
        "max_age",
    }


def test_a_condition_and_its_options_dump_only_when_set():
    assert MAINTENANCE.dump()["when"] == {
        "field": "state",
        "op": "ne",
        "value": "running",
        "check": "containers",
        "object": "nextcloud-aio-borgbackup",
        "max_age": 600,
    }
    assert Rule(field="used_pct", op="gt", value=90, level="critical", clear=85).dump() == {
        "field": "used_pct",
        "op": "gt",
        "value": 90,
        "level": "critical",
        "clear": 85,
    }
