# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Time helpers of both services: naive UTC for the tz-naive DateTime columns, in
Python (``utcnow_naive``) and as a SQL default (``utc_now_sql``), and the API's
timestamp format (``iso_utc``). Which columns are tz-naive says each service's own
``app.core.time``.
"""

from datetime import datetime, timezone

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


def utcnow_naive() -> datetime:
    """Current UTC time as a tz-naive datetime — the storage convention of the
    tz-naive DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc(dt: datetime | None) -> str | None:
    """RFC 3339 in UTC with ``Z`` — what the APIs promise with ``format: date-time``
    (R-0064, R-0202). A naive value is UTC by the storage convention; an aware one, as
    a timestamptz column hands it out in the session's zone, is converted. ``Z``, not
    ``+00:00``: the desktop readers of maintenance windows append a ``Z`` to a value
    without one, and ``…+00:00Z`` is no date."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().removesuffix("+00:00") + "Z"


class utc_now_sql(FunctionElement):
    """SQL default for tz-naive UTC columns — the DB-side twin of utcnow_naive().
    Yields the UTC wall-clock as a *naive* timestamp.

    A bare ``now()`` coerces the timestamptz in the DB *session* timezone, and the
    stack runs the postgres container with ``TZ=Europe/Berlin``, so a
    ``server_default=func.now()`` stored Berlin local time (8.14, NEU-8.14b). Since
    R-0209/R-0218 the services' sessions run in UTC, but this explicit form stays: it
    does not depend on the session, and Alembic's engine does not set it. SQLite has
    no ``timezone()``, but its ``CURRENT_TIMESTAMP`` is already UTC."""

    inherit_cache = True


@compiles(utc_now_sql, "sqlite")
def _utc_now_sql_sqlite(element, compiler, **kw) -> str:
    return "CURRENT_TIMESTAMP"


@compiles(utc_now_sql)
def _utc_now_sql_default(element, compiler, **kw) -> str:
    return "timezone('UTC', now())"
