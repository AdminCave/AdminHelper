# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""pg_engine waits for the event threads before it drops the schema (R-0509).

fire_event (app/core/events.py) hands every event to a module-wide thread pool, and its
tasks open their own sessions on the app engine, which under DATABASE_URL points at the
database pg_engine drops at the end of the session. A task still running then queried
tables that were gone and logged a traceback after a green suite. Only a session of its
own shows its end: a nested pytest session with the real conftest, in a fresh
interpreter, against a throwaway database on pg_engine's server, so that its drop_all
cannot take the tables of this session.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_SERVER_ROOT = Path(__file__).resolve().parents[1]

# The task waits at most 5 s for the drop. Without the barrier the after_drop listener
# wakes it only once the tables are gone, so the red outcome hangs on no timing; with
# the barrier the drop waits for the task, whose wait runs out while the tables stand.
_PROBE = """
import threading
from pathlib import Path

from sqlalchemy import event

from app.core import events
from app.core.database import Base, SessionLocal
from app.modules.notifications.models import NotificationSubscription

MARKER = Path(__file__).with_name("marker")


def test_an_event_task_outlives_the_test(pg_engine, monkeypatch):
    dropped = threading.Event()
    event.listen(Base.metadata, "after_drop", lambda *args, **kw: dropped.set())

    def query_after_the_drop(event_type, event_data):
        dropped.wait(5)
        db = SessionLocal()
        try:
            db.query(NotificationSubscription).count()
            result = "ok"
        except Exception as exc:
            result = type(getattr(exc, "orig", None) or exc).__name__
        finally:
            db.close()
        MARKER.write_text(result)

    monkeypatch.setattr(events, "_run_event", query_after_the_drop)
    events.fire_event("probe", None)
"""


@pytest.fixture()
def nested_session(pg_engine):
    """Runs a probe file in a nested pytest session against a throwaway database on the
    session's Postgres server; returns its exit code and its output, password masked.

    A function rather than the URL: pytest prints a failing test's arguments, and even
    the masked repr of a URL names the user, who may share the password's string."""
    dbname = f"event_teardown_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(pg_engine.url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    password = pg_engine.url.password

    def run(probe: Path) -> tuple[int, str]:
        url = pg_engine.url.set(database=dbname).render_as_string(hide_password=False)
        env = {**os.environ, "DATA_DIR": str(probe.parent / "data"), "DATABASE_URL": url}
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-p",
                    "tests.conftest",
                    "-p",
                    "no:cacheprovider",
                    "-q",
                    str(probe),
                ],
                cwd=_SERVER_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            # No traceback: the frames of subprocess.run carry env, the URL included.
            pytest.fail("the nested session did not end within 120 s", pytrace=False)
        output = proc.stdout + proc.stderr
        # Every occurrence, not a URL pattern: a driver error may echo the connection
        # string in another form.
        if password:
            output = output.replace(password, "***")
        return proc.returncode, output

    try:
        yield run
    finally:
        # Plain DROP, as test_migrations_smoke._drop_database explains; the nested
        # session's connections ended with its process.
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin_engine.dispose()


def test_the_session_end_waits_for_the_event_threads(nested_session, tmp_path):
    probe = tmp_path / "test_probe.py"
    probe.write_text(_PROBE)
    returncode, output = nested_session(probe)
    marker = probe.with_name("marker")
    result = marker.read_text() if marker.exists() else "<no marker>"
    assert (result, returncode) == ("ok", 0), (
        f"marker {result!r}, exit {returncode}, nested session:\n{output[-4000:]}"
    )
