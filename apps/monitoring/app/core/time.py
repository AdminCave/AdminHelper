# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Time helpers.

Every DateTime column in this service is tz-naive UTC (Postgres ``timestamp
without time zone``). Writing or comparing a tz-aware datetime against them makes
the result depend on the container's session timezone, so all call sites use
``utcnow_naive()`` instead of re-implementing
``datetime.now(timezone.utc).replace(tzinfo=None)`` — or, worse, a bare
``datetime.now(timezone.utc)`` that silently stays aware (audit 2.29).
"""

from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """Current UTC time as a tz-naive datetime — the storage convention of every
    DateTime column in this service (2.29)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
