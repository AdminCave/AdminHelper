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

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


def utcnow_naive() -> datetime:
    """Current UTC time as a tz-naive datetime — the storage convention of every
    DateTime column in this service (2.29)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class utc_now_sql(FunctionElement):
    """SQL default for the tz-naive DateTime columns — the DB-side twin of
    utcnow_naive(). Yields the UTC wall-clock as a *naive* timestamp.

    Dialect-portable on purpose: a bare ``now()`` default coerces the timestamptz
    in the DB *session* timezone, and prod runs the postgres container with
    ``TZ=Europe/Berlin`` — so it stored Berlin local time (NEU-8.14b). Postgres
    needs the explicit ``timezone('UTC', now())`` wrapping; SQLite (the test DB)
    has no ``timezone()`` function but its ``CURRENT_TIMESTAMP`` is already UTC."""

    inherit_cache = True


@compiles(utc_now_sql, "postgresql")
def _utc_now_sql_pg(element, compiler, **kw) -> str:
    return "timezone('UTC', now())"


@compiles(utc_now_sql, "sqlite")
def _utc_now_sql_sqlite(element, compiler, **kw) -> str:
    return "CURRENT_TIMESTAMP"


@compiles(utc_now_sql)
def _utc_now_sql_default(element, compiler, **kw) -> str:
    return "timezone('UTC', now())"
