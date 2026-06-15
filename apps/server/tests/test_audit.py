# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import contextvars

from app.core.request_context import Actor, current_actor, set_actor
from app.modules.audit import service
from app.modules.audit.models import AuditLog


def test_current_actor_defaults_to_system():
    # A fresh context (nothing bound) must yield the system actor — checked in an
    # isolated Context so it does not depend on test execution order.
    ctx = contextvars.Context()
    assert ctx.run(current_actor).actor_type == "system"


def test_set_and_read_actor():
    set_actor(Actor("user", "7", "alice", "10.0.0.5"))
    a = current_actor()
    assert (a.actor_type, a.actor_id, a.actor_label, a.source_ip) == (
        "user",
        "7",
        "alice",
        "10.0.0.5",
    )


def test_record_writes_row_with_current_actor(db_session):
    set_actor(Actor("user", "7", "alice", "10.0.0.5"))
    service.record(
        db_session,
        "connection.created",
        object_type="connection",
        object_id="abc-123",
        object_label="prod-db",
    )
    row = db_session.query(AuditLog).filter(AuditLog.action == "connection.created").one()
    assert row.actor_type == "user"
    assert row.actor_id == "7"
    assert row.actor_label == "alice"
    assert row.source_ip == "10.0.0.5"
    assert row.object_type == "connection"
    assert row.object_id == "abc-123"
    assert row.object_label == "prod-db"
    assert row.status == "success"
    assert row.timestamp is not None


def test_record_explicit_actor_overrides_context(db_session):
    set_actor(Actor("user", "7", "alice"))
    service.record(
        db_session,
        "auth.login_failed",
        status="failure",
        actor=Actor("anonymous", None, "mallory", "1.2.3.4"),
    )
    row = db_session.query(AuditLog).filter(AuditLog.action == "auth.login_failed").one()
    assert row.actor_type == "anonymous"
    assert row.actor_label == "mallory"
    assert row.status == "failure"


def test_record_is_best_effort_on_error():
    # A session whose add() fails must not raise out of record() — auditing must
    # never break the action being audited.
    class BrokenSession:
        def add(self, *args, **kwargs):
            raise RuntimeError("db down")

        def rollback(self):
            pass

    service.record(BrokenSession(), "connection.created")  # must not raise
