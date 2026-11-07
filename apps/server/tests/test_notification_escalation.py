# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1081: an unacknowledged critical incident escalates to the person's own channel.

Pinned here: after the deadline since the first critical ping and not before; not once
acknowledged or resolved; once per person; again after a reopen and a new critical
ping; not for a muted row or server, a switched-off channel or one without a target;
regardless of the matrix; the quiet hours as for critical; the history entry; and a
query count that does not grow with the candidates."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import event

from app.modules.notifications import stream_hub
from app.modules.notifications.escalation import escalate_due
from app.modules.notifications.incidents import access, act, finish_actions, ingest
from app.modules.notifications.models import (
    Notification,
    NotificationIncident,
    NotificationIncidentEvent,
    NotificationOutbox,
    NotificationServerMute,
    NotificationSettings,
)

from .test_notification_incidents import T0, _admin, _at, _check
from .test_notifications import _event, _server

NTFY = "https://ntfy.example/alerts"


@pytest.fixture()
def web01(db_session):
    return _server(db_session, "srv-1", name="web01")


@pytest.fixture()
def published(monkeypatch):
    calls: list = []
    monkeypatch.setattr(stream_hub, "publish", lambda uids, mid: calls.append(sorted(uids)))
    return calls


def _person(db, username="boss", **settings):
    user = _admin(db, username)
    values = dict(
        escalation_enabled=True,
        escalation_minutes=10,
        escalation_channel="ntfy",
        ntfy_url=NTFY,
    )
    values.update(settings)
    row = db.get(NotificationSettings, user.id)
    if row is None:
        row = NotificationSettings(user_id=user.id)
        db.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    db.commit()
    return user


def _escalations(db, user):
    return (
        db.query(NotificationOutbox)
        .filter(NotificationOutbox.user_id == user.id, NotificationOutbox.title.like("Unack%"))
        .order_by(NotificationOutbox.id)
        .all()
    )


def _incident(db):
    return db.query(NotificationIncident).one()


def _act(db, user, kind, now):
    held = access(db, user, _incident(db).id, lock=True)
    act(db, user, held, kind, now)
    finish_actions(db, [held.incident.id])


class TestDeadline:
    def test_escalates_after_the_deadline_and_not_before(self, db_session, web01, published):
        user = _person(db_session)
        ingest(db_session, _check(), now=T0)
        assert _incident(db_session).critical_since == T0

        assert escalate_due(db_session, _at(9)) == 0
        assert escalate_due(db_session, _at(10)) == 1

        (entry,) = _escalations(db_session, user)
        assert (entry.channel, entry.address, entry.severity, entry.status) == (
            "ntfy",
            NTFY,
            "critical",
            "pending",
        )
        assert entry.title == "Unacknowledged for 10 min: CPU critical on web01"
        assert entry.body == "cpu 99% > 95%"
        assert entry.created_at == _at(10)
        row = db_session.query(Notification).filter(Notification.user_id == user.id).one()
        assert row.escalated_at == _at(10)
        assert published[-1] == [user.id]

    def test_the_deadline_is_the_persons(self, db_session, web01, published):
        _person(db_session, escalation_minutes=30)
        ingest(db_session, _check(), now=T0)

        assert escalate_due(db_session, _at(29)) == 0
        assert escalate_due(db_session, _at(30)) == 1

    def test_once_per_person(self, db_session, web01, published):
        user = _person(db_session)
        ingest(db_session, _check(), now=T0)

        assert escalate_due(db_session, _at(10)) == 1
        assert escalate_due(db_session, _at(11)) == 0
        assert escalate_due(db_session, _at(60)) == 0
        assert len(_escalations(db_session, user)) == 1

    def test_the_history_names_the_channel(self, db_session, web01, published):
        _person(db_session)
        ingest(db_session, _check(), now=T0)
        escalate_due(db_session, _at(10))

        entries = [
            (e.kind, e.text, e.at)
            for e in db_session.query(NotificationIncidentEvent).order_by(
                NotificationIncidentEvent.id
            )
            if e.kind == "escalated"
        ]
        assert entries == [("escalated", "ntfy", _at(10))]

    def test_a_keyless_critical_notice_escalates(self, db_session, web01, published):
        _person(db_session)
        ingest(db_session, _event(), now=T0)
        assert _incident(db_session).critical_since == T0

        assert escalate_due(db_session, _at(10)) == 1

    def test_a_warning_does_not_escalate(self, db_session, web01, published):
        _person(db_session)
        ingest(db_session, _check("warning", severity="warning"), now=T0)

        assert _incident(db_session).critical_since is None
        assert escalate_due(db_session, _at(60)) == 0

    def test_off_does_not_escalate(self, db_session, web01, published):
        _person(db_session, escalation_enabled=False)
        ingest(db_session, _check(), now=T0)

        assert escalate_due(db_session, _at(60)) == 0


class TestStop:
    def test_not_after_the_acknowledgement(self, db_session, web01, published):
        user = _person(db_session)
        ingest(db_session, _check(), now=T0)
        _act(db_session, user, "acked", _at(5))

        assert escalate_due(db_session, _at(10)) == 0

    def test_not_after_the_check_recovered(self, db_session, web01, published):
        _person(db_session)
        ingest(db_session, _check(), now=T0)
        ingest(db_session, _check("ok"), now=_at(5))

        assert _incident(db_session).critical_since is None
        assert escalate_due(db_session, _at(10)) == 0

    def test_not_after_a_resolve_by_hand(self, db_session, web01, published):
        user = _person(db_session)
        ingest(db_session, _check(), now=T0)
        _act(db_session, user, "resolved", _at(5))

        assert _incident(db_session).critical_since is None
        assert escalate_due(db_session, _at(10)) == 0

    def test_again_after_a_reopen_and_a_new_critical_ping(self, db_session, web01, published):
        user = _person(db_session)
        ingest(db_session, _check(), now=T0)
        assert escalate_due(db_session, _at(10)) == 1
        _act(db_session, user, "resolved", _at(12))
        _act(db_session, user, "reopened", _at(13))
        row = db_session.query(Notification).filter(Notification.user_id == user.id).one()
        assert row.escalated_at is None

        # The next critical event past the reopen window pings again.
        ingest(db_session, _check(), now=_at(45))
        assert _incident(db_session).critical_since == _at(45)
        assert escalate_due(db_session, _at(54)) == 0
        assert escalate_due(db_session, _at(55)) == 1
        assert len(_escalations(db_session, user)) == 2

    def test_again_after_the_check_reopened_it(self, db_session, web01, published):
        user = _person(db_session)
        ingest(db_session, _check(), now=T0)
        assert escalate_due(db_session, _at(10)) == 1
        ingest(db_session, _check("ok"), now=_at(12))
        # Critical again inside the reopen window: the same incident opens again.
        ingest(db_session, _check(), now=_at(14))
        assert db_session.query(NotificationIncident).count() == 1
        assert _incident(db_session).critical_since == _at(14)

        assert escalate_due(db_session, _at(23)) == 0
        assert escalate_due(db_session, _at(24)) == 1
        assert len(_escalations(db_session, user)) == 2


class TestSkip:
    def test_a_muted_row(self, db_session, web01, published):
        user = _person(db_session)
        ingest(db_session, _check(), now=T0)
        row = db_session.query(Notification).filter(Notification.user_id == user.id).one()
        row.muted_until = _at(120)
        db_session.commit()

        assert escalate_due(db_session, _at(10)) == 0
        assert escalate_due(db_session, _at(121)) == 1

    def test_a_muted_server(self, db_session, web01, published):
        user = _person(db_session)
        ingest(db_session, _check(), now=T0)
        db_session.add(NotificationServerMute(user_id=user.id, server_id="srv-1", until=_at(60)))
        db_session.commit()

        assert escalate_due(db_session, _at(10)) == 0
        assert escalate_due(db_session, _at(61)) == 1

    def test_a_switched_off_channel(self, db_session, web01, published):
        _person(db_session, disabled_channels=json.dumps(["ntfy"]))
        ingest(db_session, _check(), now=T0)

        assert escalate_due(db_session, _at(10)) == 0

    def test_a_channel_without_a_target(self, db_session, web01, published):
        user = _person(db_session, ntfy_url=None)
        ingest(db_session, _check(), now=T0)

        assert escalate_due(db_session, _at(10)) == 0
        # The target added later: the escalation follows.
        db_session.get(NotificationSettings, user.id).ntfy_url = NTFY
        db_session.commit()
        assert escalate_due(db_session, _at(11)) == 1

    def test_telegram_without_a_bot_token(self, db_session, web01, published, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
        user = _person(db_session, escalation_channel="telegram")
        user.telegram_chat_id = "4711"
        db_session.commit()
        ingest(db_session, _check(), now=T0)

        assert escalate_due(db_session, _at(10)) == 0

    def test_a_matrix_without_the_channel_escalates_anyway(self, db_session, web01, published):
        user = _person(
            db_session,
            matrix=json.dumps({"critical": ["desktop"]}),
            escalation_channel="email",
        )
        ingest(db_session, _check(), now=T0)
        assert db_session.query(NotificationOutbox).count() == 0

        assert escalate_due(db_session, _at(10)) == 1
        (entry,) = _escalations(db_session, user)
        assert (entry.channel, entry.address) == ("email", "boss@example.org")


class TestQuiet:
    def test_critical_passes_by_default(self, db_session, web01, published):
        user = _person(db_session, quiet_enabled=True, quiet_start="07:00", quiet_end="09:00")
        ingest(db_session, _check(), now=T0)
        escalate_due(db_session, _at(10))

        assert [e.next_attempt_at for e in _escalations(db_session, user)] == [None]

    def test_waits_when_critical_may_not_pass(self, db_session, web01, published):
        user = _person(
            db_session,
            quiet_enabled=True,
            quiet_start="07:00",
            quiet_end="09:00",
            quiet_critical=False,
        )
        ingest(db_session, _check(), now=T0)
        escalate_due(db_session, _at(10))

        # T0 is 08:00 UTC; the person's zone is UTC.
        assert [e.next_attempt_at for e in _escalations(db_session, user)] == [
            T0 + timedelta(hours=1)
        ]


def test_the_queries_do_not_grow_with_the_candidates(db_session, published):
    def selects(n):
        for i in range(n):
            _server(db_session, f"q{n}-{i}", name=f"q{n}-{i}")
        users = [_person(db_session, f"p{n}-{i}") for i in range(n)]
        for i in range(n):
            ingest(db_session, _check(key=f"check:q{n}-{i}", server=f"q{n}-{i}"), now=T0)
        statements: list[str] = []
        connection = db_session.connection()

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(connection, "before_cursor_execute", record)
        try:
            # Every person holds every incident: n users times n incidents.
            assert escalate_due(db_session, _at(10)) == n * n
        finally:
            event.remove(connection, "before_cursor_execute", record)
        for user in users:
            db_session.get(NotificationSettings, user.id).escalation_enabled = False
        db_session.commit()
        return [s for s in statements if s.lstrip().upper().startswith("SELECT")]

    one, three = selects(1), selects(3)
    # The history cap counts per incident (finish_actions); the rest is fixed.
    assert len(three) - len(one) <= 2 * (3 - 1), (one, three)
