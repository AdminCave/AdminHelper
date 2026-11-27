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
from fnmatch import fnmatchcase


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
class DiskRules:
    """The disk rules of the host's enabled agent_resources check, for disk_forecast.

    `ignore_mounts` are fnmatch patterns: the check's ignore_mounts masked, and its no_rating
    exceptions (R-1637). `min_free_gb` is per mount (its disk_overrides entry, else
    disk_min_free_gb); `free_gb` is per mount from that check's last result, empty for an
    agent that sends none.
    """

    ignore_mounts: frozenset[str]
    min_free_gb: dict[str, float]
    default_min_free_gb: float
    free_gb: dict[str, float]

    def ignores(self, mount: str) -> bool:
        return any(fnmatchcase(mount, pattern) for pattern in self.ignore_mounts)

    def min_free_for(self, mount: str) -> float:
        return self.min_free_gb.get(mount, self.default_min_free_gb)


@dataclass(frozen=True)
class CheckContext:
    """What execute_check hands a checker with `wants_context`: its own previous
    `_details`, if a valid partner is configured, the partner's state, and for
    disk_forecast the disk rules of its host."""

    prev_details: dict | None = None
    partner: PartnerState | None = None
    disk_rules: DiskRules | None = None
