# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The server's database sessions run in UTC (R-0209).

The tz-naive DateTime columns hold naive UTC (F7), and postgres converts an aware
value with the session's TimeZone — the stack's postgres runs with TZ=Europe/Berlin.
The client asks for Berlin here through PGTZ, which libpq sends on every new
connection, so the case is red without the fix on any database, a UTC one in CI
included. The engine is the app's own, which the suite points at DATABASE_URL.
"""

import datetime
import os

import pytest
from sqlalchemy import text

from app.core import database

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip(),
    reason="needs DATABASE_URL: the app engine connects to it",
)


@pytest.fixture()
def berlin_client(monkeypatch):
    # libpq reads PGTZ when a connection is made; a pooled one keeps its old zone.
    monkeypatch.setenv("PGTZ", "Europe/Berlin")
    database.engine.dispose()
    yield database.engine
    database.engine.dispose()


def _zone(conn) -> str:
    return conn.execute(text("SHOW TimeZone")).scalar_one()


def test_the_session_runs_in_utc_although_the_client_asks_for_berlin(berlin_client):
    with berlin_client.connect() as conn:
        assert _zone(conn) == "UTC"
        conn.rollback()
        assert _zone(conn) == "UTC", "a rollback took the session zone back"
    with berlin_client.connect() as conn:  # the same pooled connection once more
        assert _zone(conn) == "UTC"


def test_an_aware_value_lands_as_naive_utc(berlin_client):
    noon = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=datetime.timezone.utc)
    with berlin_client.connect() as conn:
        conn.execute(text("CREATE TEMP TABLE tz_probe (ts timestamp)"))
        conn.execute(text("INSERT INTO tz_probe VALUES (:v)"), {"v": noon})
        stored = conn.execute(text("SELECT ts FROM tz_probe")).scalar_one()
        conn.rollback()
    assert stored == noon.replace(tzinfo=None), f"stored {stored}, expected naive UTC 12:00"
