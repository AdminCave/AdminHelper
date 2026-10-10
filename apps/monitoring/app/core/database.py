# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import DATABASE_URL

# Postgres pool as in the server service. APScheduler + agent push endpoint
# + web requests = realistically 10-15 connections peak.
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)


# Every session runs in UTC, as the server's do (R-0209): the tz-naive columns hold
# naive UTC, and postgres converts an aware value with the session's TimeZone, which
# the cluster's TZ (the stack sets Europe/Berlin) or a client's PGTZ would otherwise
# set. Not ``options=-c TimeZone=UTC`` in connect_args: a PGTZ in the environment wins
# over it (libpq sends PGTZ as a startup parameter of its own, applied after the
# options). The SET runs in autocommit, outside any transaction, so a rollback cannot
# take it back; insert=True runs it before any other listener (R-0218).
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
