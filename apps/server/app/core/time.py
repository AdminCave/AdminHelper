# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Time helpers.

Two DateTime storage conventions coexist in the schema (audit F7):
  * tz-naive UTC — the older tables (users.tokens_valid_after,
    enrollment_tokens.expires_at, frp, servers, hooks, connections). Store
    naive-UTC via ``utcnow_naive()`` instead of re-implementing
    ``datetime.now(timezone.utc).replace(tzinfo=None)`` at each call site.
  * timezone-aware — the newer audit_log and notification* tables use
    ``DateTime(timezone=True)`` and store aware datetimes.

Comparing a naive with an aware datetime raises TypeError, so a call site must
know which world a column belongs to. New tz-naive columns should use this helper.
"""

from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """Current UTC time as a tz-naive datetime — the storage convention of the
    tz-naive DateTime columns (F7)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
