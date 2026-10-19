# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An event fired in a test stays inside the test's rollback (R-0520).

fire_event (app/core/events.py) hands every event to a module-wide thread pool, and its
task opens sessions of its own through app.core.database.SessionLocal: on the app
engine, not on the connection of db_session. It saw none of the test's data, and what
it wrote it committed itself, past the rollback. With DATABASE_URL unset (the
testcontainers branch of pg_engine) the app engine even points at the dev default.
"""

from app.core import database, events


def test_an_event_opens_no_session_outside_the_test_connection(db_session, monkeypatch):
    opened = []
    real_session_local = database.SessionLocal

    def recording_session_local(*args, **kwargs):
        session = real_session_local(*args, **kwargs)
        opened.append(session.get_bind())
        return session

    # _run_event and handle_event import SessionLocal only when they run.
    monkeypatch.setattr(database, "SessionLocal", recording_session_local)

    futures = []
    executor = events._executor
    real_submit = executor.submit

    def collecting_submit(*args, **kwargs):
        future = real_submit(*args, **kwargs)
        futures.append(future)
        return future

    monkeypatch.setattr(executor, "submit", collecting_submit)

    # Known to no hook and to no notification builder: the task only reads the hook
    # table, wherever its session points, and writes nothing.
    events.fire_event("test.event-isolation", None)

    # Waiting on nothing would pass if fire_event ever bypassed the executor.
    assert len(futures) == 1, f"expected fire_event to submit 1 task, it submitted {len(futures)}"
    futures[0].result(timeout=30)

    test_connection = db_session.get_bind()
    foreign = [
        bind.engine.url.render_as_string(hide_password=True)
        for bind in opened
        if bind is not test_connection
    ]
    assert foreign == [], (
        "expected every event session on the test connection, "
        f"the event dispatch opened {len(foreign)} elsewhere: {foreign}"
    )
