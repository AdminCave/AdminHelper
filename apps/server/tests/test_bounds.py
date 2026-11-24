# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The bounded scalar types hold at both edges (input-boundary-validation, T1)."""

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.bounds import MAX_DEPTH, BigIntPk, IntPk, Offset, RequestModel

INT_MAX = 2147483647
BIGINT_MAX = 9223372036854775807


@pytest.mark.parametrize(
    "bound,lowest,highest",
    [
        (IntPk, 1, INT_MAX),
        (BigIntPk, 1, BIGINT_MAX),
        (Offset, 0, INT_MAX),
    ],
)
def test_bound_accepts_its_own_edges(bound, lowest, highest):
    adapter = TypeAdapter(bound)
    assert adapter.validate_python(lowest) == lowest
    assert adapter.validate_python(highest) == highest


@pytest.mark.parametrize(
    "bound,too_low,too_high",
    [
        (IntPk, 0, INT_MAX + 1),
        (BigIntPk, 0, BIGINT_MAX + 1),
        (Offset, -1, INT_MAX + 1),
    ],
)
def test_bound_rejects_the_first_value_past_each_edge(bound, too_low, too_high):
    adapter = TypeAdapter(bound)
    for value in (too_low, too_high):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)


_BOUND_KEYS = ("maximum", "minimum", "exclusiveMaximum", "exclusiveMinimum")


def _bounds(node, path="$"):
    """Every (path, value) of a numeric bound anywhere in an OpenAPI schema."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _BOUND_KEYS and isinstance(value, (int, float)):
                yield f"{path}.{key}", value
            else:
                yield from _bounds(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _bounds(item, f"{path}[{i}]")


def test_no_bound_past_2_53_is_published_as_a_float():
    # Past 2**53 a float no longer holds every integer, and FastAPI types the bounds
    # of a request body as float: BIGINT_MAX came out as 9.223372036854776e+18.
    from app.main import app

    floats = [(p, v) for p, v in _bounds(app.openapi()) if isinstance(v, float) and abs(v) >= 2**53]
    assert floats == []


def test_the_bigint_bound_is_published_exactly():
    from fastapi.responses import JSONResponse

    from app.main import app

    exact = [p for p, v in _bounds(app.openapi()) if v == BIGINT_MAX and isinstance(v, int)]
    assert exact, "no bound in the schema is the BIGINT maximum"
    # /openapi.json is off without SERVER_ENABLE_DOCS (R-0699); the route renders
    # app.openapi() through a JSONResponse, so render it the same way.
    text = JSONResponse(app.openapi()).body.decode()
    assert "9223372036854775807" in text
    assert "9.223372036854776e+18" not in text


def _nest(levels: int, leaf: Any = None) -> dict:
    """{"a": {"a": … leaf}}: `leaf` (default {}) sits `levels` keys below the dict."""
    value: Any = {} if leaf is None else leaf
    for _ in range(levels):
        value = {"a": value}
    return value


class _Body(RequestModel):
    data: dict[str, Any]


def test_a_body_may_nest_up_to_the_limit():
    # "data" is one level, so the innermost dict sits MAX_DEPTH keys below the body.
    body = {"data": _nest(MAX_DEPTH - 1)}
    assert _Body.model_validate(body).data == body["data"]


@pytest.mark.parametrize("leaf", [{}, []], ids=["dict", "list"])
def test_one_level_past_the_limit_is_refused_at_its_place(leaf):
    with pytest.raises(ValidationError) as excinfo:
        _Body.model_validate({"data": _nest(MAX_DEPTH, leaf)})
    [error] = excinfo.value.errors()
    assert error["loc"] == ("data", *("a",) * MAX_DEPTH)
    assert error["msg"] == f"Value error, must not nest deeper than {MAX_DEPTH} levels"
    # The refusal does not echo the deep subtree back.
    assert error["input"] is None


def test_a_body_far_past_the_limit_is_refused_not_a_recursion_error():
    with pytest.raises(ValidationError):
        _Body.model_validate({"data": _nest(100_000)})
