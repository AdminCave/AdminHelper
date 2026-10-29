# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tables per check type stay in step with CHECK_TYPES (R-0694).

check_types.py names the types; the checker registry, the config models and the metric
names keep their own table per type next to their users. A type missing from one of them
shows only at runtime: a ValueError from get_checker, a config nobody validates, a metrics
query for monitor_check_duration_ms that finds nothing. Nothing else compares them.
"""

import inspect

from app.check_configs import CONFIG_MODELS
from app.check_types import PUSH_ONLY_TYPES, VALID_CHECK_TYPES
from app.checkers import _REGISTRY, get_checker
from app.routers.checks import _DYNAMIC_METRIC_PATTERNS, CHECK_TYPE_METRICS


def _drift(table: set[str]) -> dict[str, list[str]]:
    return {
        "missing": sorted(VALID_CHECK_TYPES - table),
        "extra": sorted(table - VALID_CHECK_TYPES),
    }


def test_every_table_knows_exactly_the_check_types():
    tables = {
        "checkers._REGISTRY": set(_REGISTRY),
        "check_configs.CONFIG_MODELS": set(CONFIG_MODELS),
        "routers.checks.CHECK_TYPE_METRICS": set(CHECK_TYPE_METRICS),
    }
    drift = {name: _drift(types) for name, types in tables.items() if types != VALID_CHECK_TYPES}
    assert drift == {}


def test_the_dynamic_metric_patterns_name_only_check_types():
    assert set(_DYNAMIC_METRIC_PATTERNS) <= VALID_CHECK_TYPES


def test_the_type_set_is_not_empty():
    assert len(VALID_CHECK_TYPES) >= 12
    assert PUSH_ONLY_TYPES
    assert PUSH_ONLY_TYPES < VALID_CHECK_TYPES


def test_every_push_checker_takes_the_previous_details():
    # routers/agent.py hands every push checker the previous _details (PushChecker).
    signatures = {}
    for check_type in sorted(PUSH_ONLY_TYPES):
        params = inspect.signature(get_checker(check_type).evaluate).parameters
        signatures[check_type] = (list(params), params.get("prev_details", None))
    assert len(signatures) >= 7
    wrong = {
        t: names
        for t, (names, prev) in signatures.items()
        if names != ["config", "report", "prev_details"] or prev.default is not None
    }
    assert wrong == {}


def test_every_scheduled_type_has_a_runner():
    for check_type in sorted(VALID_CHECK_TYPES - PUSH_ONLY_TYPES):
        assert callable(getattr(get_checker(check_type), "run", None)), check_type
