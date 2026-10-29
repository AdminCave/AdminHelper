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

import re
from typing import Annotated, Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_core import InitErrorDetails

# Rows a list endpoint skips. Not a column width — SQL OFFSET takes a bigint,
# and unbounded the value reached it and raised (OverflowError on SQLite,
# NumericValueOutOfRange on Postgres) before a response existed. Capped at
# INTEGER per the design gate: past the last row every offset returns the same
# empty page, so a wider one buys nothing.
Offset = Annotated[int, Field(ge=0, le=2147483647)]

# A value stored in a plain Column(Integer) that is not a key — the signed INTEGER
# range, as in the server's bounds.py (R-0052). Without it the published schema had
# no upper bound, and a value past the column failed only in the database driver.
IntColumn = Annotated[int, Field(ge=-2147483648, le=2147483647)]

# A day of the week, 0 = Monday — the domain of a weekly maintenance window.
Weekday = Annotated[int, Field(ge=0, le=6)]

# The length of a weekly maintenance window, at most a day: the evaluator's
# day_offset loop relies on that cap (schemas.MaintenanceInput._kind_fields).
WindowMinutes = Annotated[int, Field(ge=1, le=1440)]


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _unstorable(text: str) -> str | None:
    """Why `text` can be neither stored nor answered, if it cannot."""
    if "\x00" in text:
        return "must not contain a NUL byte"
    if _LONE_SURROGATE.search(text):
        return "must not contain a lone surrogate (U+D800 to U+DFFF)"
    return None


def find_unstorable(data: dict) -> tuple[tuple, str, str] | None:
    """Location, value and reason of a string in `data` that _unstorable refuses,
    if any.

    Walks with an explicit stack rather than recursion: the body is whatever the
    client nested, and a RecursionError here would be the 500 this exists to
    prevent."""
    stack: list[tuple[tuple, Any]] = [((), data)]
    while stack:
        loc, value = stack.pop()
        if isinstance(value, str):
            if reason := _unstorable(value):
                return loc, value, reason
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and (reason := _unstorable(key)):
                    return (*loc, key), key, reason
                stack.append(((*loc, key), item))
        elif isinstance(value, list):
            stack.extend(((*loc, i), item) for i, item in enumerate(value))
    return None


def _refuse_unstorable(data: Any, title: str) -> Any:
    # Anything that is not a dict passes through untouched and meets its own
    # type check. The rejection is a ValidationError carrying the string's own
    # location, which pydantic merges into the field path — a ValueError here
    # would only say ["body"].
    if not isinstance(data, dict):
        return data
    found = find_unstorable(data)
    if found is None:
        return data
    loc, value, reason = found
    raise ValidationError.from_exception_data(
        title,
        [
            InitErrorDetails(
                type="value_error",
                loc=loc,
                input=value,
                ctx={"error": ValueError(reason)},
            )
        ],
    )


class RequestModel(BaseModel):
    """Base of every schema that describes a request body: no string anywhere in
    it may carry a NUL byte or a lone surrogate. A copy of the server's class of
    the same name, like the rest of this file (see the module docstring).

    Postgres stores no 0x00 in a text value: psycopg raises DataError while
    binding it, before the query runs. A lone surrogate (U+D800 to U+DFFF; JSON
    spells one only as an escape, \\ud800) has no UTF-8 form: the driver cannot
    bind it to a text column either. Where a route stores a value as json.dumps
    text (a check's config), the escape went into the row, and every later
    response carrying that row was a 500."""

    @model_validator(mode="before")
    @classmethod
    def _reject_unstorable_anywhere(cls, data: Any) -> Any:
        return _refuse_unstorable(data, cls.__name__)
