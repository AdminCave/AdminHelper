# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded scalar types for values that travel into a database column.

An unbounded ``int`` on a path, query or body field is accepted by FastAPI up to
Python's arbitrary precision and only fails in the driver: Postgres answers a
value wider than the column with NumericValueOutOfRange, which reaches the
client as HTTP 500 instead of 422. Each type below carries the *technical* width
of the column its value ends up in, so the rejection happens at the edge and the
generated OpenAPI schema states the limit.

Careful at the call site: a constraint carried in ``Annotated`` is silently
dropped when the parameter's default is a ``Query()``/``Path()`` instance —
``offset: Offset = Query(0)`` generates no ``maximum`` at all. Put the marker
into the ``Annotated`` metadata instead (``offset: Annotated[Offset, Query()] =
0``) or leave the default a plain value.
"""

from typing import Annotated, Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_core import InitErrorDetails

# Primary key of a table declared as Column(Integer) — Postgres INTEGER.
IntPk = Annotated[int, Field(ge=1, le=2147483647)]

# Primary key of a table declared as Column(BigInteger) — Postgres BIGINT.
# Careful when reading the generated schema: FastAPI types `maximum` as a float
# (fastapi.openapi.models.Schema), so in a REQUEST BODY this bound is published
# as 9.223372036854776e+18 — one more than it is. Validation is unaffected
# (pydantic keeps the int), the published contract is off by one at the very top
# of the range. Path and query parameters take a different code path and stay
# exact.
BigIntPk = Annotated[int, Field(ge=1, le=9223372036854775807)]

# A value stored in a plain Column(Integer) that is not a key — the signed
# INTEGER range, and nothing narrower. A port is 1-65535 and a limit is rarely
# negative, but tightening beyond the column is a product decision this feature
# did not make; it only moves the rejection from the driver to the edge.
IntColumn = Annotated[int, Field(ge=-2147483648, le=2147483647)]

# Rows a list endpoint skips. Not a column width — SQL OFFSET takes a bigint —
# but capped at INTEGER per the design gate: past the last row every offset
# returns the same empty page, so a wider one buys nothing.
Offset = Annotated[int, Field(ge=0, le=2147483647)]


def _find_nul(data: dict) -> tuple[tuple, str] | None:
    """Location and value of a string in `data` that carries a NUL, if any.

    Walks with an explicit stack rather than recursion: the body is whatever the
    client nested, and a RecursionError here would be the 500 this exists to
    prevent."""
    stack: list[tuple[tuple, Any]] = [((), data)]
    while stack:
        loc, value = stack.pop()
        if isinstance(value, str):
            if "\x00" in value:
                return loc, value
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and "\x00" in key:
                    return (*loc, key), key
                stack.append(((*loc, key), item))
        elif isinstance(value, list):
            stack.extend(((*loc, i), item) for i, item in enumerate(value))
    return None


class RequestModel(BaseModel):
    """Base of every schema that describes a request body: no string anywhere in
    it may carry a NUL byte.

    Postgres stores no 0x00 in a text value: psycopg raises DataError while
    binding the parameter, before the query runs, so the route never produced a
    response at all — HTTP 500. Deliberately only that byte, not control
    characters in general: the TOML guards in frp/schemas.py are a separate
    concern with their own reason.

    A model_validator, not a per-field type: the rule is a property of the input
    as a whole, and a subclass cannot forget it on a new field. mode="before"
    sees the raw input, so anything that is not a dict passes through untouched
    and meets the model's own type check — the uncaught TypeError that
    _validate_tags once raised on a raw bool is the failure this avoids.

    The rejection is raised as a ValidationError carrying the NUL's own
    location, which pydantic merges into the field path: the client sees
    loc ["body", "server_ids", 1], not just ["body"]."""

    @model_validator(mode="before")
    @classmethod
    def _reject_nul_anywhere(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        found = _find_nul(data)
        if found is None:
            return data
        loc, value = found
        raise ValidationError.from_exception_data(
            cls.__name__,
            [
                InitErrorDetails(
                    type="value_error",
                    loc=loc,
                    input=value,
                    ctx={"error": ValueError("must not contain a NUL byte")},
                )
            ],
        )
