# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The suite's engine runs its sessions in UTC like the app's (R-0225).

The app sets every connection to UTC (``app/core/database.py``, R-0209). An engine
without that listener runs in the database's default zone — Europe/Berlin locally,
UTC in CI — and the suite would see another session than the app. The client asks
for Berlin here through PGTZ, which libpq sends on every new connection, so the case
is red without the listener on any database, a UTC one in CI included.
"""

import pytest
from sqlalchemy import text


@pytest.fixture()
def berlin_client(pg_engine, monkeypatch):
    # libpq reads PGTZ when a connection is made; a pooled one keeps its old zone.
    monkeypatch.setenv("PGTZ", "Europe/Berlin")
    pg_engine.dispose()
    yield pg_engine
    pg_engine.dispose()


def _zone(conn) -> str:
    return conn.execute(text("SHOW TimeZone")).scalar_one()


def test_the_suite_engine_runs_in_utc_although_the_client_asks_for_berlin(berlin_client):
    with berlin_client.connect() as conn:
        assert _zone(conn) == "UTC"
        conn.rollback()  # what db_session does at the end of every test
        assert _zone(conn) == "UTC", "a rollback took the session zone back"
    with berlin_client.connect() as conn:  # the pooled connection the next test gets
        assert _zone(conn) == "UTC"
