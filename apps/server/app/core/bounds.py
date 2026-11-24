# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded scalar types for values that travel into a database column, and the base of
every request body schema. The shared part is ah_common.bounds (the column widths, the
NUL/surrogate/depth refusal); the key widths below are the server's own.
"""

from typing import Annotated

from pydantic import Field

from ah_common.bounds import (
    BIGINT_MAX,
    MAX_DEPTH,
    IntColumn,
    Offset,
    RequestModel,
    find_unstorable,
)

__all__ = [
    "BIGINT_MAX",
    "MAX_DEPTH",
    "BigIntPk",
    "IntColumn",
    "IntPk",
    "Offset",
    "RequestModel",
    "find_unstorable",
]

# Primary key of a table declared as Column(Integer) — Postgres INTEGER.
IntPk = Annotated[int, Field(ge=1, le=2147483647)]

# Primary key of a table declared as Column(BigInteger) — Postgres BIGINT. Path and query
# parameters publish the bound exactly; a request body needs app/core/openapi.py (see
# BIGINT_MAX).
BigIntPk = Annotated[int, Field(ge=1, le=BIGINT_MAX)]
