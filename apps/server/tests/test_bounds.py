# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The bounded scalar types hold at both edges (input-boundary-validation, T1)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.bounds import BigIntPk, IntPk, Offset

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
    from fastapi.testclient import TestClient

    from app.main import app

    exact = [p for p, v in _bounds(app.openapi()) if v == BIGINT_MAX and isinstance(v, int)]
    assert exact, "no bound in the schema is the BIGINT maximum"
    text = TestClient(app).get(app.openapi_url).text
    assert "9223372036854775807" in text
    assert "9.223372036854776e+18" not in text
