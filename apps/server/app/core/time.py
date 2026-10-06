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
know which world a column belongs to. New tz-naive columns should use these helpers
(``utcnow_naive()`` in Python, ``utc_now_sql()`` for a column server_default).
"""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer, WithJsonSchema
from sqlalchemy import func


def utcnow_naive() -> datetime:
    """Current UTC time as a tz-naive datetime — the storage convention of the
    tz-naive DateTime columns (F7)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_now_sql():
    """SQL default for tz-naive UTC columns — the DB-side twin of utcnow_naive().

    ``timezone('UTC', now())`` yields the UTC wall-clock as a *naive* timestamp
    regardless of the database session's timezone. A bare ``func.now()`` coerces in
    the session TZ, and the stack runs the postgres container with
    ``TZ=Europe/Berlin`` — so ``server_default=func.now()`` stored Berlin local time
    while the application writes UTC via ``utcnow_naive()`` (8.14)."""
    return func.timezone("UTC", func.now())


def iso_utc(dt: datetime | None) -> str | None:
    """RFC 3339 in UTC with ``Z`` — what the API promises with ``format: date-time``
    (R-0064). A naive value is UTC by the storage convention above; an aware one,
    as a timestamptz column hands it out in the session's zone, is converted."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().removesuffix("+00:00") + "Z"


# A response field that is written with iso_utc(). The JSON schema stays
# string/date-time: a bare PlainSerializer would turn it into a plain string.
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(iso_utc, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]
