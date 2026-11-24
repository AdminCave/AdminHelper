# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Request-edge bounds of both services: integer widths of database columns and the base
of every request body schema.

An unbounded ``int`` on a path, query or body field is accepted by FastAPI up to
Python's arbitrary precision and only fails in the driver: Postgres answers a value
wider than the column with NumericValueOutOfRange, which reaches the client as HTTP 500
instead of 422. Each type carries the *technical* width of the column its value ends up
in, so the rejection happens at the edge and the generated OpenAPI schema states the
limit. Service-specific bounds stay in each service's ``app.core.bounds``.

Careful at the call site: a constraint carried in ``Annotated`` is silently dropped when
the parameter's default is a ``Query()``/``Path()`` instance — ``offset: Offset =
Query(0)`` generates no ``maximum`` at all. Put the marker into the ``Annotated``
metadata instead (``offset: Annotated[Offset, Query()] = 0``) or leave the default a
plain value.
"""

import re
from typing import Annotated, Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_core import InitErrorDetails

# The upper bound of a Column(BigInteger) — Postgres BIGINT. FastAPI types `maximum` as a
# float (fastapi.openapi.models.Schema), so in a REQUEST BODY this bound would be published
# as 9.223372036854776e+18, above the real limit; the server's app/core/openapi.py writes
# the exact int back into the schema. Validation is unaffected (pydantic keeps the int).
BIGINT_MAX = 9223372036854775807

# A value stored in a plain Column(Integer) that is not a key — the signed INTEGER range,
# and nothing narrower. A port is 1-65535 and a limit is rarely negative, but tightening
# beyond the column is a product decision; this only moves the rejection from the driver
# to the edge (R-0052).
IntColumn = Annotated[int, Field(ge=-2147483648, le=2147483647)]

# Rows a list endpoint skips. Not a column width — SQL OFFSET takes a bigint, and
# unbounded the value reached it and raised (OverflowError on SQLite,
# NumericValueOutOfRange on Postgres) before a response existed. Capped at INTEGER per
# the design gate: past the last row every offset returns the same empty page, so a wider
# one buys nothing.
Offset = Annotated[int, Field(ge=0, le=2147483647)]


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


# What a text column cannot take: Postgres keeps no NUL in a text value, and the driver
# cannot encode a lone surrogate (U+D800 to U+DFFF) — nor can a response that later carries
# the stored text. A request body refuses both at its boundary (RequestModel,
# find_unstorable); a text with no sender to refuse is replaced (storable).
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


def _replaced(value: Any, pattern: re.Pattern[str]) -> Any:
    """`value` with every `pattern` match in its strings, dict keys included, as U+FFFD.

    Recursive like the json.dumps that writes the value: the service builds it, so the
    depth is the service's."""
    if isinstance(value, str):
        return pattern.sub("\ufffd", value)
    if isinstance(value, dict):
        return {
            (_replaced(key, pattern) if isinstance(key, str) else key): _replaced(item, pattern)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_replaced(item, pattern) for item in value]
    return value


def storable(value: Any) -> Any:
    """`value` with every NUL and lone surrogate replaced, so a text column takes it."""
    return _replaced(value, _UNSTORABLE)


def readable(value: Any) -> Any:
    """`value` read from a stored JSON column with every lone surrogate replaced, so a
    response can encode it; an older row may hold one as an escape (\\ud800)."""
    return _replaced(value, _LONE_SURROGATE)


def _unstorable(text: str) -> str | None:
    """Why `text` can be neither stored nor answered, if it cannot."""
    if "\x00" in text:
        return "must not contain a NUL byte"
    if _LONE_SURROGATE.search(text):
        return "must not contain a lone surrogate (U+D800 to U+DFFF)"
    return None


# How deep a request body may nest, counted from the body: a dict or list whose location
# has more segments is refused. Far beyond any body the clients send (the agent report
# stays under ten), far below what the encoders of a stored value and of a response carry.
MAX_DEPTH = 32
_TOO_DEEP = f"must not nest deeper than {MAX_DEPTH} levels"


def find_unstorable(data: dict) -> tuple[tuple, str | None, str] | None:
    """Location, value and reason of a string in `data` that _unstorable refuses, or of a
    dict or list nested deeper than MAX_DEPTH, if any. For the latter the value is None: a
    refusal echoes its input, and the input is the deep subtree.

    Walks with an explicit stack rather than recursion: the body is whatever the client
    nested, and a RecursionError here would be the 500 this exists to prevent."""
    stack: list[tuple[tuple, Any]] = [((), data)]
    while stack:
        loc, value = stack.pop()
        if isinstance(value, dict | list) and len(loc) > MAX_DEPTH:
            return loc, None, _TOO_DEEP
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


def refuse_unstorable(data: Any, title: str) -> Any:
    """`data` unchanged, or a ValidationError for what find_unstorable finds in it.

    Anything that is not a dict passes through untouched and meets its own type check.
    The ValidationError carries the string's own location, which pydantic merges into the
    field path — a ValueError here would only say ["body"]."""
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
    """Base of every schema that describes a request body: no string anywhere in it may
    carry a NUL byte or a lone surrogate, and nothing in it may nest deeper than MAX_DEPTH.

    Postgres stores no 0x00 in a text value: psycopg raises DataError while binding the
    parameter, before the query runs, so the route never produced a response at all —
    HTTP 500. A lone surrogate (U+D800 to U+DFFF; JSON spells one only as an escape,
    \\ud800) has no UTF-8 form: psycopg cannot bind it to a text column either, and
    JSONResponse cannot write it. Where a route stores a value as json.dumps text (tags, a
    check's config), the escape went into the row, and every later response carrying that
    row was a 500. Deliberately only these two, not control characters in general.

    A model_validator, not a per-field type: the rule is a property of the input as a
    whole, and a subclass cannot forget it on a new field. mode="before" sees the raw
    input, so anything that is not a dict meets the model's own type check."""

    @model_validator(mode="before")
    @classmethod
    def _reject_unstorable_anywhere(cls, data: Any) -> Any:
        return refuse_unstorable(data, cls.__name__)
