# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from sqlalchemy.orm import DeclarativeBase, sessionmaker

from ah_common.database import make_engine, session_dependency
from app.core.config import DATABASE_URL, DB_MAX_OVERFLOW, DB_POOL_SIZE

# APScheduler + agent push endpoint + web requests = realistically 10-15 connections
# at peak with the default 10+20.
engine = make_engine(DATABASE_URL, pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


get_db = session_dependency(SessionLocal)
