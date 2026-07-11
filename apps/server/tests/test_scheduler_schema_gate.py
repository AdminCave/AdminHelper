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
