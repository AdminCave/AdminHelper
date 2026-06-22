# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Phase D: the notification outbox drain delivers pending e-mail entries out of
the request path, with retry/backoff and a permanent-failure cutoff."""

from datetime import datetime, timedelta, timezone

from app.modules.notifications import outbox as outbox_mod
from app.modules.notifications.models import Notification, NotificationOutbox
from app.modules.notifications.outbox import drain_outbox

from .test_notifications import _user


def _notif(db, user, title="CPU critical on web01", body="Port 22: refused"):
    n = Notification(
        user_id=user.id,
        severity="critical",
        category="monitoring",
        event_type="monitoring.check.transition",
        title=title,
        body=body,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def _outbox(db, notif, user, **kw):
    defaults = dict(
        notification_id=notif.id,
        user_id=user.id,
        channel="email",
        address="alice@example.com",
        status="pending",
        attempts=0,
    )
    defaults.update(kw)
    o = NotificationOutbox(**defaults)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


class TestDrain:
    def test_sends_pending_email_with_notification_content(self, db_session, monkeypatch):
        calls = []
        monkeypatch.setattr(
            outbox_mod, "send_email", lambda to, subj, body: calls.append((to, subj, body))
        )
        user = _user(db_session, "alice", email="alice@example.com")
        notif = _notif(db_session, user)
        entry = _outbox(db_session, notif, user)

        sent, failed = drain_outbox(db_session)

        assert (sent, failed) == (1, 0)
        assert calls == [("alice@example.com", "CPU critical on web01", "Port 22: refused")]
        db_session.refresh(entry)
        assert entry.status == "sent"
        assert entry.sent_at is not None
        assert entry.attempts == 1

    def test_failure_schedules_retry(self, db_session, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(outbox_mod, "send_email", boom)
        user = _user(db_session, "alice", email="alice@example.com")
        entry = _outbox(db_session, _notif(db_session, user), user)

        sent, failed = drain_outbox(db_session)

        assert (sent, failed) == (0, 0)  # not permanently failed yet
        db_session.refresh(entry)
        assert entry.status == "pending"
        assert entry.attempts == 1
        assert entry.next_attempt_at is not None
        assert "connection refused" in entry.last_error

    def test_marks_failed_after_max_attempts(self, db_session, monkeypatch):
        monkeypatch.setattr(outbox_mod, "NOTIFICATION_MAX_ATTEMPTS", 2)
        monkeypatch.setattr(
            outbox_mod, "send_email", lambda *a, **k: (_ for _ in ()).throw(OSError("nope"))
        )
        user = _user(db_session, "alice", email="alice@example.com")
        entry = _outbox(db_session, _notif(db_session, user), user, attempts=1)

        sent, failed = drain_outbox(db_session)

        assert (sent, failed) == (0, 1)
        db_session.refresh(entry)
        assert entry.status == "failed"
        assert entry.attempts == 2

    def test_skips_telegram_channel(self, db_session, monkeypatch):
        calls = []
        monkeypatch.setattr(outbox_mod, "send_email", lambda *a, **k: calls.append(a))
        user = _user(db_session, "alice")
        entry = _outbox(
            db_session, _notif(db_session, user), user, channel="telegram", address="123"
        )

        sent, failed = drain_outbox(db_session)

        assert (sent, failed) == (0, 0)
        assert calls == []
        db_session.refresh(entry)
        assert entry.status == "pending"  # untouched, ships later

    def test_respects_future_next_attempt_at(self, db_session, monkeypatch):
        calls = []
        monkeypatch.setattr(outbox_mod, "send_email", lambda *a, **k: calls.append(a))
        user = _user(db_session, "alice", email="alice@example.com")
        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        _outbox(db_session, _notif(db_session, user), user, next_attempt_at=future)

        sent, failed = drain_outbox(db_session)

        assert (sent, failed) == (0, 0)
        assert calls == []
