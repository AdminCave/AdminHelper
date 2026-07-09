# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tz-naive DateTime columns store UTC (F7). Their server_default must yield
UTC-naive regardless of the DB session timezone — a bare now() default coerced in
the session TZ (the stack runs postgres with TZ=Europe/Berlin), storing local time
~1-2h off UTC (8.14). Verified against the real Postgres (AH_TEST_DB)."""

from datetime import timedelta

from sqlalchemy import text

from app.core.time import utcnow_naive
from app.modules.api_keys.models import ApiKey


def test_server_default_stores_utc_regardless_of_session_timezone(db_session):
    # Force a non-UTC session TZ for this transaction. With the old
    # ``server_default=now()`` the naive coercion would store Berlin wall-clock
    # (UTC + 1-2h); ``timezone('UTC', now())`` must stay UTC.
    db_session.execute(text("SET LOCAL TIME ZONE 'Europe/Berlin'"))
    key = ApiKey(name="k", hashed_key="h", permission="read")
    db_session.add(key)
    db_session.flush()  # emit the INSERT so the DB evaluates the default now
    db_session.refresh(key)

    assert key.created_at is not None
    assert key.created_at.tzinfo is None  # stored tz-naive
    drift = abs(key.created_at - utcnow_naive())
    assert drift < timedelta(minutes=5), f"created_at is not UTC-naive (drift {drift})"
