# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded scalar types for values that travel into a database column.

Declared here rather than imported: monitoring is its own service with its own
database and shares no code with the server, and the same file exists there for
the same reason (apps/server/app/core/bounds.py).

Careful at the call site: a constraint carried in ``Annotated`` is silently
dropped when the parameter's default is a ``Query()``/``Path()`` instance —
``offset: Offset = Query(0)`` generates no ``maximum`` at all. Put the marker
into the ``Annotated`` metadata instead (``offset: Annotated[Offset, Query()] =
0``) or leave the default a plain value.
"""

from typing import Annotated, Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_core import InitErrorDetails

# Rows a list endpoint skips. Not a column width — SQL OFFSET takes a bigint,
# and unbounded the value reached it and raised (OverflowError on SQLite,
# NumericValueOutOfRange on Postgres) before a response existed. Capped at
# INTEGER per the design gate: past the last row every offset returns the same
# empty page, so a wider one buys nothing.
Offset = Annotated[int, Field(ge=0, le=2147483647)]


def _find_nul(data: dict) -> tuple[tuple, str] | None:
    """Location and value of a string in `data` that carries a NUL, if any.

    Postgres stores no 0x00 in a text value; psycopg raises DataError while
    binding it, before the query runs. Walks with an explicit stack rather than
    recursion: the body is whatever the client nested, and a RecursionError here
    would be the 500 this exists to prevent."""
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


def _refuse_nul(data: Any, title: str) -> Any:
    # Anything that is not a dict passes through untouched and meets its own
    # type check. The rejection is a ValidationError carrying the NUL's own
    # location, which pydantic merges into the field path — a ValueError here
    # would only say ["body"].
    if not isinstance(data, dict):
        return data
    found = _find_nul(data)
    if found is None:
        return data
    loc, value = found
    raise ValidationError.from_exception_data(
        title,
        [
            InitErrorDetails(
                type="value_error",
                loc=loc,
                input=value,
                ctx={"error": ValueError("must not contain a NUL byte")},
            )
        ],
    )


class RequestModel(BaseModel):
    """Base of every schema that describes a request body: no string anywhere in
    it may carry a NUL byte. A copy of the server's class of the same name, like
    the rest of this file (see the module docstring)."""

    @model_validator(mode="before")
    @classmethod
    def _reject_nul_anywhere(cls, data: Any) -> Any:
        return _refuse_nul(data, cls.__name__)
