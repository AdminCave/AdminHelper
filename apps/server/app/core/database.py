# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from sqlalchemy import create_engine
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
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
