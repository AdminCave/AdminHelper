# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Database engine and session dependency of both services. Each service keeps its own
``engine``, ``SessionLocal`` and ``Base`` (separate databases, separate metadata) and
builds them with these helpers."""

from collections.abc import Callable, Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def set_session_utc(dbapi_connection, connection_record) -> None:
    """``connect`` listener: every session runs in UTC.

    The tz-naive columns hold naive UTC (F7), and postgres converts an aware value with
    the session's TimeZone, which the cluster's TZ (the stack sets Europe/Berlin) or a
    client's PGTZ would otherwise set. Not ``options=-c TimeZone=UTC`` in connect_args: a
    PGTZ in the environment wins over it (libpq sends PGTZ as a startup parameter of its
    own, applied after the options). The SET runs in autocommit, outside any transaction,
    so a rollback cannot take it back (R-0209, R-0218)."""
    autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    cursor = dbapi_connection.cursor()
    cursor.execute("SET TIME ZONE 'UTC'")
    cursor.close()
    dbapi_connection.autocommit = autocommit


def make_engine(url: str, *, pool_size: int, max_overflow: int) -> Engine:
    """Postgres pool, per process. With WEB_CONCURRENCY=N the total is
    N*(pool_size+max_overflow) — watch Postgres max_connections. pool_pre_ping catches
    dead connections after restarts."""
    engine = create_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    # insert=True: the UTC session comes before any other connect listener.
    event.listen(engine, "connect", set_session_utc, insert=True)
    return engine


def session_dependency(session_factory: sessionmaker) -> Callable[[], Iterator[Session]]:
    """A FastAPI dependency yielding one session per request, closed afterwards."""

    def get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    return get_db
