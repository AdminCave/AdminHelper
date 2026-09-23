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
