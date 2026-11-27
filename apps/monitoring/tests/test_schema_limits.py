# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Length bounds of the admin API's free strings (R-1792, R-1827): a server id is at
most 255 characters, a text in a rule at most 1024, a list in a rule at most
MAX_FIELDS values. Each bound is read back from the published schema as well, since
an Annotated alias can lose a Field constraint without a word."""

import pytest
from pydantic import ValidationError

from app import schemas
from app.catalog.model import MAX_FIELDS

_SERVER_ID_FIELDS = [
    (
        schemas.CheckCreate,
        "server_id",
        {"name": "c", "check_type": "ping", "config": {"target": "192.0.2.1"}},
    ),
    (schemas.CheckUpdate, "server_id", {}),
    (schemas.AlertRuleCreate, "match_server_id", None),
    (schemas.AlertRuleUpdate, "match_server_id", {}),
    (schemas.TemplateAssign, "server_id", None),
    (schemas.MaintenanceInput, "server_id", None),
    (schemas.ExceptionInput, "scope_value", None),
]


def _max_lengths(schema: dict) -> set[int]:
    """Every maxLength anywhere in a field's JSON schema (through anyOf and items)."""
    found = set()
    if isinstance(schema, dict):
        if "maxLength" in schema:
            found.add(schema["maxLength"])
        for v in schema.values():
            found |= _max_lengths(v)
    elif isinstance(schema, list):
        for v in schema:
            found |= _max_lengths(v)
    return found


@pytest.mark.parametrize("model,field,_", _SERVER_ID_FIELDS)
def test_server_id_fields_publish_their_bound(model, field, _):
    prop = model.model_json_schema()["properties"][field]
    assert _max_lengths(prop) == {255}, prop


@pytest.mark.parametrize("model,field,base", [f for f in _SERVER_ID_FIELDS if f[2] is not None])
def test_a_server_id_longer_than_255_is_refused(model, field, base):
    model.model_validate({**base, field: "s" * 255})
    with pytest.raises(ValidationError, match="at most 255"):
        model.model_validate({**base, field: "s" * 256})


def test_rule_value_bounds_are_published():
    prop = schemas.RuleOverride.model_json_schema()["properties"]["value"]
    assert _max_lengths(prop) == {1024}, prop
    lists = [b for b in prop["anyOf"] if b.get("type") == "array"]
    assert [b.get("maxItems") for b in lists] == [MAX_FIELDS]


def test_a_rule_text_longer_than_1024_is_refused():
    schemas.RuleOverride.model_validate({"value": "v" * 1024})
    schemas.RuleOverride.model_validate({"value": ["v" * 1024]})
    with pytest.raises(ValidationError):
        schemas.RuleOverride.model_validate({"value": "v" * 1025})
    with pytest.raises(ValidationError):
        schemas.RuleOverride.model_validate({"value": ["v" * 1025]})


def test_a_rule_list_longer_than_max_fields_is_refused():
    schemas.RuleOverride.model_validate({"value": list(range(MAX_FIELDS))})
    with pytest.raises(ValidationError):
        schemas.RuleOverride.model_validate({"value": list(range(MAX_FIELDS + 1))})


def test_an_exception_scope_value_longer_than_255_is_refused():
    base = {"scope_kind": "server", "effect": "no_notify", "duration_kind": "permanent"}
    schemas.ExceptionInput.model_validate({**base, "scope_value": "s" * 255})
    with pytest.raises(ValidationError, match="at most 255"):
        schemas.ExceptionInput.model_validate({**base, "scope_value": "s" * 256})
