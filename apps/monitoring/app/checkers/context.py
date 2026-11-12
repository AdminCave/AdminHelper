# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What execute_check hands a checker with `wants_context` (R-1224).

A module of its own so that a checker module can import it: app.checkers imports
every checker module before it defines anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PartnerState:
    """The stored state of the agent check paired with a central one (`pair_check_id`).

    `status` is "pending" while the partner has no state yet; `sensor` is the
    partner's probe sensor (tls, certfile, http) as its config names it.
    """

    check_id: str
    sensor: str | None
    status: str
    details: dict | None
    last_check: datetime | None


@dataclass(frozen=True)
class CheckContext:
    """What execute_check hands a checker with `wants_context`: its own previous
    `_details` and, if a valid partner is configured, the partner's state."""

    prev_details: dict | None = None
    partner: PartnerState | None = None
