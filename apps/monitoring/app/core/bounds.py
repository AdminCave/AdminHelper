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

from typing import Annotated

from pydantic import Field

# Rows a list endpoint skips. Not a column width — SQL OFFSET takes a bigint,
# and unbounded the value reached it and raised (OverflowError on SQLite,
# NumericValueOutOfRange on Postgres) before a response existed. Capped at
# INTEGER per the design gate: past the last row every offset returns the same
# empty page, so a wider one buys nothing.
Offset = Annotated[int, Field(ge=0, le=2147483647)]
