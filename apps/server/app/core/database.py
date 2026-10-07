# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import DATABASE_URL, DB_MAX_OVERFLOW, DB_POOL_SIZE

# Postgres pool, per process. Single-worker default (10+20) is realistically
# 15-20 connections at peak. With WEB_CONCURRENCY=N the total is N*(size+overflow)
# — tune DB_POOL_SIZE/DB_MAX_OVERFLOW down for many workers, watch Postgres
# max_connections. pool_pre_ping catches dead connections after restarts.
engine = create_engine(
    DATABASE_URL,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=3600,
)


# Every session runs in UTC: the tz-naive columns hold naive UTC (F7), and postgres
# converts an aware value with the session's TimeZone, which the cluster's TZ (the
# stack sets Europe/Berlin) or a client's PGTZ would otherwise set. Not
# ``options=-c TimeZone=UTC`` in connect_args: a PGTZ in the server's environment wins
# over it (libpq sends PGTZ as a startup parameter of its own, applied after the
# options). The SET runs in autocommit, outside any transaction, so a rollback cannot
# take it back; insert=True runs it before any other listener (R-0209).
@event.listens_for(engine, "connect", insert=True)
def _session_utc(dbapi_connection, connection_record):
    autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    cursor = dbapi_connection.cursor()
    cursor.execute("SET TIME ZONE 'UTC'")
    cursor.close()
    dbapi_connection.autocommit = autocommit


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
