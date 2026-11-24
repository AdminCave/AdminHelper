# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scheduler must not schedule jobs against a not-yet-migrated schema (4.73).

On an update the old schema exists, so the scheduler process starts fine even if the
migration failed/is pending — and APScheduler would then swallow the job exceptions,
running outbox drain / cleanups against a stale schema while looking healthy. The gate
must abort instead when alembic_version isn't at head.
"""

from contextlib import contextmanager

import pytest

from app import scheduler_main


def _patch_schema(monkeypatch, head, current):
    """Stub the alembic head lookup + the DB's current revision, and neuter the DB
    connection so the gate runs without a real database."""
    import alembic.runtime.migration as arm
    import alembic.script as ascript

    import app.core.database as db

    monkeypatch.setattr(
        ascript.ScriptDirectory,
        "from_config",
        lambda cfg: type("SD", (), {"get_current_head": lambda self: head})(),
    )
    monkeypatch.setattr(
        arm.MigrationContext,
        "configure",
        lambda conn, **kw: type("MC", (), {"get_current_revision": lambda self: current})(),
    )

    @contextmanager
    def _fake_connect():
        yield object()

    monkeypatch.setattr(db.engine, "connect", _fake_connect)


def test_scheduler_aborts_when_schema_not_at_head(monkeypatch):
    _patch_schema(monkeypatch, head="headrev", current="oldrev")
    with pytest.raises(SystemExit):
        scheduler_main._wait_for_schema_head(retries=2, interval=0)


def test_scheduler_proceeds_when_schema_at_head(monkeypatch):
    _patch_schema(monkeypatch, head="headrev", current="headrev")
    # Returns without raising — the schema is at head, so jobs may be scheduled.
    scheduler_main._wait_for_schema_head(retries=2, interval=0)


def test_scheduler_fires_server_startup_once_and_drains_events_on_stop(monkeypatch):
    """server.startup comes from the one scheduler process, after its jobs are scheduled;
    the stop waits for running events (R-0689)."""
    import types

    import app.core.events as events
    import app.core.logging_config as logging_config
    from app.modules.hooks import scheduler as hooks_scheduler

    calls = []
    for name in dir(hooks_scheduler):
        if name.startswith("schedule_") or name == "reconcile_scheduled_hooks":
            monkeypatch.setattr(hooks_scheduler, name, lambda: None)
    monkeypatch.setattr(
        hooks_scheduler,
        "scheduler",
        types.SimpleNamespace(
            start=lambda: calls.append("scheduler.start"),
            shutdown=lambda wait: calls.append(f"scheduler.shutdown(wait={wait})"),
        ),
    )
    monkeypatch.setattr(logging_config, "configure_logging", lambda: None)
    monkeypatch.setattr(scheduler_main, "_wait_for_schema_head", lambda: None)
    monkeypatch.setattr(events, "fire_event", lambda t, d: calls.append(f"fire {t}"))
    monkeypatch.setattr(events, "shutdown_events", lambda: calls.append("shutdown_events"))
    monkeypatch.setattr(scheduler_main.signal, "signal", lambda sig, handler: None)

    class _Stopped:
        # The stop signal has arrived: wait returns at once.
        def set(self):
            pass

        def wait(self):
            calls.append("stop")

    # Swap the module attribute, not threading.Event: that would replace it for the whole process.
    monkeypatch.setattr(scheduler_main, "threading", types.SimpleNamespace(Event=_Stopped))

    scheduler_main.main()

    assert calls == [
        "scheduler.start",
        "fire server.startup",
        "stop",
        "scheduler.shutdown(wait=False)",
        "shutdown_events",
    ]


def test_the_web_lifespan_fires_no_server_startup(monkeypatch):
    """WEB_CONCURRENCY workers each run the lifespan; none of them fires server.startup."""
    import asyncio

    import app.core.events as events
    import app.main as m
    from app.modules.notifications import stream_hub

    fired = []
    monkeypatch.setattr(m, "_run_startup_tasks", lambda: None)
    monkeypatch.setattr(events, "fire_event", lambda t, d: fired.append(t))

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(stream_hub, "start", _noop)
    monkeypatch.setattr(stream_hub, "stop", _noop)

    async def scenario():
        async with m.lifespan(m.app):
            pass

    asyncio.run(scenario())
    assert fired == []
