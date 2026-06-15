# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import types
from datetime import datetime, timedelta, timezone

from app.core.request_context import Actor, actor_from_request, bind_actor
from app.modules.audit import service
from app.modules.audit.models import AuditLog


def _entry(days_ago: int) -> AuditLog:
    return AuditLog(
        actor_type="system",
        action="connection.created",
        status="success",
        timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )


def _fake_request():
    """A minimal stand-in with a settable .state, like a Starlette Request."""
    req = types.SimpleNamespace()
    req.state = types.SimpleNamespace()
    return req


def test_actor_defaults_to_system_when_unbound():
    assert actor_from_request(_fake_request()).actor_type == "system"


def test_bind_and_read_actor():
    req = _fake_request()
    bind_actor(req, Actor("user", "7", "alice", "10.0.0.5"))
    a = actor_from_request(req)
    assert (a.actor_type, a.actor_id, a.actor_label, a.source_ip) == (
        "user",
        "7",
        "alice",
        "10.0.0.5",
    )


def test_record_writes_row(db_session):
    service.record(
        db_session,
        "connection.created",
        actor=Actor("user", "7", "alice", "10.0.0.5"),
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


def test_record_defaults_to_system_actor(db_session):
    service.record(db_session, "server.startup")
    row = db_session.query(AuditLog).filter(AuditLog.action == "server.startup").one()
    assert row.actor_type == "system"
    assert row.actor_id is None


def test_record_is_best_effort_on_error():
    # A session whose add() fails must not raise out of record() — auditing must
    # never break the action being audited.
    class BrokenSession:
        def add(self, *args, **kwargs):
            raise RuntimeError("db down")

        def rollback(self):
            pass

    service.record(BrokenSession(), "connection.created")  # must not raise


def test_cleanup_removes_only_old_entries(db_session):
    db_session.add_all([_entry(days_ago=400), _entry(days_ago=10)])
    db_session.commit()

    removed = service.cleanup_old_entries(db_session, retention_days=365)

    assert removed == 1
    assert db_session.query(AuditLog).count() == 1


def test_cleanup_disabled_keeps_everything(db_session):
    db_session.add(_entry(days_ago=9999))
    db_session.commit()

    assert service.cleanup_old_entries(db_session, retention_days=0) == 0
    assert db_session.query(AuditLog).count() == 1
