# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from sqlalchemy.orm import DeclarativeBase, sessionmaker

from ah_common.database import make_engine, session_dependency
from app.core import events  # noqa: F401  registers the session listeners of queue_event
from app.core.config import DATABASE_URL, DB_MAX_OVERFLOW, DB_POOL_SIZE

# Single-worker default (10+20) is realistically 15-20 connections at peak; tune
# DB_POOL_SIZE/DB_MAX_OVERFLOW down for many workers.
engine = make_engine(DATABASE_URL, pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


get_db = session_dependency(SessionLocal)
