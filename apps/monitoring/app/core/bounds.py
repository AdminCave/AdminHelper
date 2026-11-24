# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded scalar types for values that travel into a database column, and the base of
every request body schema. The shared part is ah_common.bounds (the column widths, the
NUL/surrogate/depth refusal, storable/readable); the domains below are monitoring's own.
"""

from typing import Annotated

from pydantic import Field

from ah_common.bounds import (
    MAX_DEPTH,
    IntColumn,
    Offset,
    RequestModel,
    find_unstorable,
    readable,
    storable,
)

__all__ = [
    "CREDENTIAL_REF_MAX",
    "CREDENTIAL_REF_PATTERN",
    "MAX_DEPTH",
    "IntColumn",
    "Offset",
    "RequestModel",
    "Weekday",
    "WindowMinutes",
    "find_unstorable",
    "readable",
    "storable",
]

# A day of the week, 0 = Monday — the domain of a weekly maintenance window.
Weekday = Annotated[int, Field(ge=0, le=6)]

# The length of a weekly maintenance window, at most a day: the evaluator's
# day_offset loop relies on that cap (schemas.MaintenanceInput._kind_fields).
WindowMinutes = Annotated[int, Field(ge=1, le=1440)]


# <module id>/<instance key>/<slot>: the key of a secret in the host's credential file,
# never the secret. No segment starts with a dot, so none reads as a way up. The agent's
# credentials block reports these keys too (discovery.clean_credentials).
CREDENTIAL_REF_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:@-]*(/[A-Za-z0-9][A-Za-z0-9_.:@-]*)*$"
CREDENTIAL_REF_MAX = 255
