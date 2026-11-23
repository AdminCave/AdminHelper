# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""queue_event fires once the session's transaction commits, and never if it does not (R-0689).

The pool is bounded (MAX_PENDING) and shutdown_events waits a bounded time for it.
"""

import logging
import threading
from concurrent.futures import Future

import pytest

from app.core import events

EVENT = "test.after-commit"


class _RecordingExecutor:
    def __init__(self, *, finished=True, error=None):
        self.calls = []
        self.futures = []
        self._finished = finished
        self._error = error

    def submit(self, fn, /, *args, **kwargs):
        if self._error is not None:
            raise self._error
        self.calls.append(args)
        future = Future()
        if self._finished:
            future.set_result(None)
        self.futures.append(future)
        return future


@pytest.fixture()
def executor(monkeypatch):
    recorder = _RecordingExecutor()
    monkeypatch.setattr(events, "_executor", recorder)
    return recorder


@pytest.fixture()
def stalled(monkeypatch):
    # Futures that never finish, as a hanging hook leaves them; cancelled at the end so
    # nothing stays counted against MAX_PENDING for the next test.
    recorder = _RecordingExecutor(finished=False)
    monkeypatch.setattr(events, "_executor", recorder)
    yield recorder
    for future in recorder.futures:
        future.cancel()
    assert events._pending == set()


def test_commit_fires_the_queued_event_once(db_session, executor):
    events.queue_event(db_session, EVENT, {"id": 7})
    assert executor.calls == []

    db_session.commit()
    db_session.commit()

    assert executor.calls == [(EVENT, {"id": 7})]


def test_rollback_drops_the_queued_event(db_session, executor):
    events.queue_event(db_session, EVENT, {"id": 7})
    db_session.rollback()
    db_session.commit()

    assert executor.calls == []


def test_close_drops_the_queued_event(db_session, executor):
    events.queue_event(db_session, EVENT, {"id": 7})
    db_session.close()
    db_session.commit()

    assert executor.calls == []


def test_a_savepoint_commit_waits_for_the_outer_commit(db_session, executor):
    with db_session.begin_nested():
        events.queue_event(db_session, EVENT, {"id": 7})
    assert executor.calls == []

    db_session.commit()
    assert executor.calls == [(EVENT, {"id": 7})]


def test_a_failed_dispatch_leaves_the_commit_standing(db_session, monkeypatch, caplog):
    monkeypatch.setattr(events, "_executor", _RecordingExecutor(error=RuntimeError("pool down")))
    events.queue_event(db_session, EVENT, {"id": 7})

    with caplog.at_level(logging.ERROR, logger=events.__name__):
        db_session.commit()

    assert [r.getMessage() for r in caplog.records] == [
        f"Event dispatch after commit failed (event={EVENT})"
    ]
    assert db_session.info.get(events._QUEUED_KEY) is None


def test_past_max_pending_an_event_is_dropped_with_a_warning(stalled, caplog):
    with caplog.at_level(logging.WARNING, logger=events.__name__):
        for _ in range(events.MAX_PENDING + 2):
            events.fire_event(EVENT, None)

    assert len(stalled.calls) == events.MAX_PENDING
    assert [r.getMessage() for r in caplog.records] == [
        f"Event queue full ({events.MAX_PENDING}), event {EVENT} dropped"
    ] * 2

    stalled.futures[0].set_result(None)
    events.fire_event(EVENT, None)
    assert len(stalled.calls) == events.MAX_PENDING + 1


def test_shutdown_waits_for_a_running_event(stalled, caplog):
    events.fire_event(EVENT, "finishes")
    (finishing,) = stalled.futures
    threading.Timer(0.05, finishing.set_result, args=(None,)).start()

    # The generous timeout is only a ceiling: shutdown_events returns once the event is done.
    with caplog.at_level(logging.WARNING, logger=events.__name__):
        events.shutdown_events(timeout=30)

    assert finishing.result() is None
    assert caplog.records == []


def test_shutdown_drops_what_has_not_started_after_the_timeout(stalled, caplog):
    events.fire_event(EVENT, "queued")
    events.fire_event(EVENT, "hangs")
    queued, hanging = stalled.futures
    hanging.set_running_or_notify_cancel()

    # This test is about the deadline itself: neither future can finish, so the short
    # timeout always runs out.
    with caplog.at_level(logging.WARNING, logger=events.__name__):
        events.shutdown_events(timeout=0.1)

    assert queued.cancelled()
    assert not hanging.done()
    assert [r.getMessage() for r in caplog.records] == [
        "Shutdown: 2 event(s) unfinished after 0.1 s, 1 dropped"
    ]
    hanging.set_result(None)


def test_shutdown_with_nothing_pending_returns_at_once(executor, caplog):
    events.fire_event(EVENT, None)

    with caplog.at_level(logging.WARNING, logger=events.__name__):
        events.shutdown_events(timeout=30)

    assert caplog.records == []
