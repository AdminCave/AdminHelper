# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A NUL byte anywhere in a request body is refused by the model.

In JSON a NUL is spelled \\u0000, so the raw bytes of a body never contain one
and the path/query middleware cannot see it — only the parsed value does. Every
request schema inherits RequestModel, whose before-validator walks that value.
The route-level cases live with the schemas that use it (test_text_bounds.py);
this file pins the mechanism itself."""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError, field_validator

from app.core.bounds import RequestModel

NUL = chr(0)


class _Inner(BaseModel):
    note: str = ""


class _Body(RequestModel):
    name: str = ""
    ids: list[str] = []
    extra: dict[str, Any] = {}
    inner: _Inner | None = None


@pytest.mark.parametrize(
    ("payload", "loc"),
    [
        ({"name": "a" + NUL}, ("name",)),
        ({"ids": ["ok", NUL]}, ("ids", 1)),
        ({"extra": {"k": {"deep": [NUL]}}}, ("extra", "k", "deep", 0)),
        ({"extra": {"k" + NUL: 1}}, ("extra", "k" + NUL)),
        ({"inner": {"note": NUL}}, ("inner", "note")),
        # A field the model does not declare is ignored by pydantic, but the rule
        # is about the input, not about the fields someone remembered.
        ({"undeclared": NUL}, ("undeclared",)),
    ],
)
def test_a_nul_anywhere_is_a_value_error_at_its_own_place(payload, loc):
    with pytest.raises(ValidationError) as exc:
        _Body.model_validate(payload)
    errors = exc.value.errors()
    assert [(e["type"], e["loc"]) for e in errors] == [("value_error", loc)]
    assert errors[0]["msg"] == "Value error, must not contain a NUL byte"


def test_clean_input_passes_unchanged():
    # Not a control-character guard: a tab, a newline and a DEL all pass.
    body = _Body.model_validate(
        {"name": "a\tb\nc\x7fd", "ids": ["ä€"], "extra": {"k": [1, None, True]}}
    )
    assert body.name == "a\tb\nc\x7fd"
    assert body.ids == ["ä€"]
    assert body.extra == {"k": [1, None, True]}


# The raw values a mode="before" validator can be handed, after BAD_TAGS in
# test_frp_input_hardening.py: _validate_tags once met a bool with .strip() and
# answered 500. Anything that is not a dict must reach the model's own type
# check and come back as its model_type error — a NUL inside it included.
@pytest.mark.parametrize("raw", [None, 7, True, "a" + NUL, ["a" + NUL], [{"name": NUL}]])
def test_a_non_dict_input_meets_the_models_own_type_check(raw):
    with pytest.raises(ValidationError) as exc:
        _Body.model_validate(raw)
    assert [e["type"] for e in exc.value.errors()] == ["model_type"]


def test_a_subclass_validator_is_not_displaced():
    class _Tagged(RequestModel):
        tags: list[str] = []

        @field_validator("tags", mode="before")
        @classmethod
        def _lower(cls, v: Any) -> Any:
            return [t.lower() for t in v]

    assert _Tagged.model_validate({"tags": ["A"]}).tags == ["a"]
    with pytest.raises(ValidationError):
        _Tagged.model_validate({"tags": ["A" + NUL]})


def test_a_deeply_nested_body_is_walked_without_recursion():
    # Deeper than the interpreter's recursion limit: a recursive walk would die
    # with RecursionError — not a ValidationError, so the route would answer 500.
    deep: Any = NUL
    for _ in range(5000):
        deep = [deep]
    with pytest.raises(ValidationError) as exc:
        _Body.model_validate({"extra": {"k": deep}})
    assert exc.value.errors()[0]["type"] == "value_error"
