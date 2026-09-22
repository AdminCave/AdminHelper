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

from typing import Annotated

from pydantic import AfterValidator, Field

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


def _reject_nul(value: str) -> str:
    # Postgres stores no 0x00 in a text value: psycopg raises DataError while
    # binding the parameter, before the query runs, so the route never produced a
    # response at all. Rejecting at the edge turns that 500 into a 422.
    if "\x00" in value:
        raise ValueError("must not contain a NUL byte")
    return value


# A text value that travels into a Postgres text column or a comparison against
# one. Deliberately narrow: this rejects the one byte the database refuses, not
# control characters in general — the TOML guards in frp/schemas.py are a
# separate concern with their own reason.
SafeText = Annotated[str, AfterValidator(_reject_nul)]
