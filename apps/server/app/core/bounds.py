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

from pydantic import Field

# Primary key of a table declared as Column(Integer) — Postgres INTEGER.
IntPk = Annotated[int, Field(ge=1, le=2147483647)]

# Primary key of a table declared as Column(BigInteger) — Postgres BIGINT.
BigIntPk = Annotated[int, Field(ge=1, le=9223372036854775807)]

# Rows a list endpoint skips. Not a column width — SQL OFFSET takes a bigint —
# but capped at INTEGER per the design gate: past the last row every offset
# returns the same empty page, so a wider one buys nothing.
Offset = Annotated[int, Field(ge=0, le=2147483647)]
