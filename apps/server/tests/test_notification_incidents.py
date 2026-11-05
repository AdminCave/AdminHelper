# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The hub folds the events of a check into one incident of the bell (R-1079).

Pinned here: folding, silent reopening and new incidents; the ping rule the
monitoring service applied before (tests/test_alerter_hub.py there: one problem
per REOPEN_WINDOW, an escalation at once, an all-clear only of what the bell
showed and at that level, nothing caught up); bundles with fixed members and the
least privilege of their texts; keyless notices; muting; the history cap; the
retention of incidents; the ingress fields and alert.triggered."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.modules.notifications import stream_hub
from app.modules.notifications.incidents import HISTORY_MAX, REOPEN_WINDOW, ingest
from app.modules.notifications.models import (
    Notification,
    NotificationIncident,
    NotificationIncidentEvent,
    NotificationIncidentMember,
    NotificationOutbox,
    NotificationServerMute,
)
from app.modules.notifications.schemas import IncomingEvent
from app.modules.notifications.service import cleanup_old_notifications, notify_users

from .test_notifications import _event, _server, _sub, _user

T0 = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)


def _at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _check(
    new_status="critical", *, severity="critical", key="check:1", server="srv-1", rules=None
):
    return IncomingEvent(
        event_type="monitoring.check.transition",
        severity=severity,
        category="monitoring",
        title=f"CPU {new_status} on web01",
        body="cpu 99% > 95%",
        source_type="server",
        source_id=server,
        new_status=new_status,
        incident_key=key,
        rules=rules,
    )


def _heartbeats(servers, new_status="critical", *, title="Agents not reporting"):
    return IncomingEvent(
        event_type="monitoring.check.transition",
        severity="critical",
        category="monitoring",
        title=title,
        body="Heartbeat lost" if new_status != "ok" else "Heartbeat back",
        source_type="server",
        source_ids=list(servers),
        incident_keys=[f"hb:{s}" for s in servers],
        new_status=new_status,
    )


def _heartbeat(server, new_status="critical"):
    return IncomingEvent(
        event_type="monitoring.check.transition",
        severity="critical",
        category="monitoring",
        title=f"Heartbeat {new_status} on {server}",
        source_type="server",
        source_id=server,
        new_status=new_status,
        incident_key=f"hb:{server}",
    )


def _incidents(db):
    return db.query(NotificationIncident).order_by(NotificationIncident.id).all()


def _rows(db, user):
    return (
        db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.id)
    ).all()


def _history(db, incident):
    return [
        (e.kind, e.server_id)
        for e in db.query(NotificationIncidentEvent)
        .filter(NotificationIncidentEvent.incident_id == incident.id)
        .order_by(NotificationIncidentEvent.id)
    ]


def _pings(db, user):
    """The titles of the user's e-mails in order: one per ping."""
    return [
        e.title
        for e in db.query(NotificationOutbox)
        .filter(NotificationOutbox.user_id == user.id)
        .order_by(NotificationOutbox.id)
    ]


def _admin(db, username="boss", **sub):
    user = _user(db, username, is_admin=True, email=f"{username}@example.org")
    _sub(db, user, email=True, **sub)
    return user


@pytest.fixture()
def published(monkeypatch):
    calls: list = []
    monkeypatch.setattr(stream_hub, "publish", lambda uids, mid: calls.append(sorted(uids)))
    return calls


@pytest.fixture()
def web01(db_session):
    return _server(db_session, "srv-1", name="web01")


# --- folding --------------------------------------------------------------------


class TestFolding:
    def test_the_events_of_a_check_fold_into_one_incident(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("warning"), now=_at(5))
        ingest(db_session, _check("critical"), now=_at(10))

        (incident,) = _incidents(db_session)
        assert (incident.key, incident.state, incident.event_count) == ("check:1", "open", 3)
        assert (incident.first_at, incident.last_at) == (_at(0), _at(10))
        assert len(_rows(db_session, admin)) == 1
        assert _history(db_session, incident) == [
            ("triggered", None),
            ("notified", None),
            ("triggered", None),
            ("triggered", None),
        ]

    def test_a_resolved_incident_reopens_silently_inside_the_window(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("ok"), now=_at(1))
        (row,) = _rows(db_session, admin)
        row.read_at = _at(2)
        db_session.commit()

        ingest(db_session, _check("critical"), now=_at(10))

        (incident,) = _incidents(db_session)
        assert (incident.state, incident.resolved_at, incident.event_count) == ("open", None, 2)
        assert _history(db_session, incident)[-1] == ("reopened", None)
        (row,) = _rows(db_session, admin)
        assert (row.read_at, row.notified_at) == (_at(2), _at(1)), "a reopening is silent"

    def test_after_the_window_a_new_incident_opens(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("ok"), now=_at(1))
        ingest(db_session, _check("critical"), now=_at(31))

        first, second = _incidents(db_session)
        assert (first.state, second.state) == ("resolved", "open")
        assert len(_rows(db_session, admin)) == 2

    def test_a_check_moved_to_another_server_opens_an_incident_there(self, db_session, web01):
        db01 = _server(db_session, "srv-2", name="db01")
        reader = _user(db_session, "reader", servers=[db01])
        _sub(db_session, reader)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("critical", server="srv-2"), now=_at(5))
        ingest(db_session, _check("ok", server="srv-2"), now=_at(6))

        old, moved = _incidents(db_session)
        assert (old.source_id, old.state, old.event_count) == ("srv-1", "open", 1)
        assert (moved.source_id, moved.state, moved.event_count) == ("srv-2", "resolved", 1)
        assert _history(db_session, old) == [("triggered", None)]
        assert [r.incident_id for r in _rows(db_session, reader)] == [moved.id]

    def test_a_recovery_on_another_server_is_not_the_incidents(self, db_session, web01):
        _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("ok", server="srv-2"), now=_at(1))
        (incident,) = _incidents(db_session)
        assert incident.state == "open", "an active incident resolves only on its server"

        incident.state = "resolved"
        db_session.commit()
        before = _history(db_session, incident)
        ingest(db_session, _check("ok", server="srv-2"), now=_at(2))
        assert _history(db_session, incident) == before, "nor takes a silent entry"

    def test_rules_and_text_of_the_last_problem_are_on_the_incident(self, db_session, web01):
        _admin(db_session)
        rules = [{"name": "Ops mail", "channel": "email", "ok": True}]
        ingest(db_session, _check("warning", rules=rules), now=_at(0))

        (incident,) = _incidents(db_session)
        assert incident.title == "CPU warning on web01"
        assert incident.source_id == "srv-1"
        assert incident.severity == "warning"
        assert incident.rules == '[{"name": "Ops mail", "channel": "email", "ok": true}]'


# --- the ping rule (the monitoring service's hub_decision, moved here) ----------


class TestPingRule:
    def test_one_problem_ping_per_window_and_nothing_caught_up(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("ok"), now=_at(1))  # the all-clear of what it showed
        ingest(db_session, _check("critical"), now=_at(10))  # inside the window: silent
        ingest(db_session, _check("ok"), now=_at(11))  # the bell never showed it: silent
        ingest(db_session, _check("critical"), now=_at(31))

        assert _pings(db_session, admin) == [
            "CPU critical on web01",
            "CPU ok on web01",
            "CPU critical on web01",
        ]

    def test_the_window_is_thirty_minutes(self, db_session, web01):
        admin = _admin(db_session)
        assert REOPEN_WINDOW == timedelta(minutes=30)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("warning"), now=_at(29.9))
        assert len(_pings(db_session, admin)) == 1
        # An improvement after the window is shown again (critical -> warning).
        ingest(db_session, _check("warning"), now=_at(30))
        assert _pings(db_session, admin) == ["CPU critical on web01", "CPU warning on web01"]
        assert _incidents(db_session)[0].notified_severity == "warning"

    def test_an_escalation_of_a_shown_warning_pings_at_once_and_reopens_an_ack(
        self, db_session, web01
    ):
        admin = _admin(db_session)
        ingest(db_session, _check("warning"), now=_at(0))
        (incident,) = _incidents(db_session)
        incident.state, incident.acked_by, incident.acked_at = "acked", admin.id, _at(1)
        db_session.commit()

        ingest(db_session, _check("critical"), now=_at(5))

        assert _pings(db_session, admin) == ["CPU warning on web01", "CPU critical on web01"]
        (incident,) = _incidents(db_session)
        assert (incident.state, incident.acked_by, incident.acked_at) == ("open", None, None)
        assert (incident.notified_severity, incident.last_notified_at) == ("critical", _at(5))
        assert ("escalated", None) in _history(db_session, incident)

    def test_an_improvement_is_silent_and_the_all_clear_keeps_the_shown_level(
        self, db_session, web01
    ):
        # A subscriber of critical saw the alarm and has to see the all-clear, though
        # the recovery arrives as warning (worse of warning and ok).
        _admin(db_session)
        crit = _user(db_session, "crit", is_admin=True)
        _sub(db_session, crit, min_severity="critical")
        ingest(db_session, _check("critical"), now=_at(0))
        (row,) = _rows(db_session, crit)
        row.read_at = _at(1)
        db_session.commit()
        ingest(db_session, _check("warning"), now=_at(5))
        assert _rows(db_session, crit)[0].read_at == _at(1)

        ingest(db_session, _check("ok", severity="warning"), now=_at(6))

        (row,) = _rows(db_session, crit)
        assert (row.title, row.severity, row.read_at) == ("CPU ok on web01", "critical", None)
        assert _incidents(db_session)[0].notified_severity == "ok"

    def test_a_capped_check_never_escalates_and_its_all_clear_stays_capped(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical", severity="warning"), now=_at(0))
        ingest(db_session, _check("critical", severity="warning"), now=_at(5))
        (incident,) = _incidents(db_session)
        assert (incident.severity, incident.notified_severity) == ("warning", "warning")
        assert len(_pings(db_session, admin)) == 1

        # The severity raised in between does not lift the all-clear.
        ingest(db_session, _check("ok", severity="critical"), now=_at(6))
        assert _rows(db_session, admin)[0].severity == "warning"
        assert len(_pings(db_session, admin)) == 2

    def test_capped_level_info_opens_nothing(self, db_session, web01):
        admin = _admin(db_session, min_severity="info")
        ingest(db_session, _check("critical", severity="info"), now=_at(0))
        ingest(db_session, _check("pending"), now=_at(1))
        assert _incidents(db_session) == []
        assert _rows(db_session, admin) == []

    def test_a_recovery_without_a_shown_problem_pings_nobody(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("ok"), now=_at(0))
        assert (_incidents(db_session), _rows(db_session, admin)) == ([], [])

    def test_a_recovery_of_an_incident_resolved_by_hand_is_a_silent_entry(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)
        incident.state, incident.resolved_by, incident.resolved_at = "resolved", admin.id, _at(1)
        db_session.commit()

        ingest(db_session, _check("ok"), now=_at(2))

        (incident,) = _incidents(db_session)
        assert (incident.resolved_by, incident.resolved_at) == (admin.id, _at(1))
        assert _history(db_session, incident)[-1] == ("resolved", None)
        assert len(_pings(db_session, admin)) == 1

    def test_a_ping_and_nothing_else_nudges_the_stream(self, db_session, web01, published):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("critical"), now=_at(5))
        assert published == [[admin.id]]


# --- the recipients' rows -------------------------------------------------------


class TestRows:
    def test_a_ping_moves_the_row_up_unread_and_shown_again(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (row,) = _rows(db_session, admin)
        row_id = row.id
        row.read_at, row.hidden_at = _at(1), _at(1)
        db_session.commit()

        ingest(db_session, _check("warning"), now=_at(40))

        (row,) = _rows(db_session, admin)
        assert row.id == row_id
        assert (row.notified_at, row.read_at, row.hidden_at) == (_at(40), None, None)
        assert row.title == "CPU warning on web01"

    def test_a_silent_fold_leaves_the_row_alone(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (row,) = _rows(db_session, admin)
        row.read_at = _at(1)
        db_session.commit()

        ingest(db_session, _check("warning"), now=_at(10))

        (row,) = _rows(db_session, admin)
        assert (row.title, row.notified_at, row.read_at) == (
            "CPU critical on web01",
            _at(0),
            _at(1),
        )

    def test_an_outbox_entry_keeps_the_text_of_its_ping(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("ok"), now=_at(1))

        assert _rows(db_session, admin)[0].title == "CPU ok on web01"
        assert _pings(db_session, admin) == ["CPU critical on web01", "CPU ok on web01"]

    def test_the_notified_entry_names_the_channels(self, db_session, web01):
        _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        entry = (
            db_session.query(NotificationIncidentEvent)
            .filter(NotificationIncidentEvent.kind == "notified")
            .one()
        )
        assert entry.text == "bell, email"

    def test_a_new_recipient_gets_a_row_at_the_next_ping(self, db_session, web01):
        _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        late = _user(db_session, "late", is_admin=True)
        _sub(db_session, late)
        ingest(db_session, _check("critical"), now=_at(10))
        assert _rows(db_session, late) == []
        ingest(db_session, _check("critical"), now=_at(30))
        (row,) = _rows(db_session, late)
        assert row.incident_id == _incidents(db_session)[0].id


# --- muting ---------------------------------------------------------------------


class TestMute:
    def test_a_muted_incident_takes_the_content_but_stays_read_and_silent(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (row,) = _rows(db_session, admin)
        row.read_at, row.muted_until = _at(1), _at(120)
        db_session.commit()

        ingest(db_session, _check("warning"), now=_at(40))

        (row,) = _rows(db_session, admin)
        assert (row.title, row.read_at, row.notified_at) == ("CPU warning on web01", _at(1), _at(0))
        assert len(_pings(db_session, admin)) == 1
        assert [k for k, _ in _history(db_session, _incidents(db_session)[0])].count(
            "notified"
        ) == 1

    def test_an_expired_mute_lets_the_ping_through(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (row,) = _rows(db_session, admin)
        row.read_at, row.muted_until = _at(1), _at(35)
        db_session.commit()

        ingest(db_session, _check("warning"), now=_at(40))

        assert _rows(db_session, admin)[0].read_at is None
        assert len(_pings(db_session, admin)) == 2

    def test_a_server_mute_keeps_the_row_of_a_new_incident_read(self, db_session, web01):
        admin = _admin(db_session)
        other = _admin(db_session, "other")
        db_session.add(NotificationServerMute(user_id=admin.id, server_id="srv-1", until=_at(60)))
        db_session.commit()

        ingest(db_session, _check("critical"), now=_at(0))

        (row,) = _rows(db_session, admin)
        assert row.read_at == _at(0)
        assert _pings(db_session, admin) == []
        assert _rows(db_session, other)[0].read_at is None
        assert len(_pings(db_session, other)) == 1

    def test_a_server_mute_does_not_silence_a_bundle_of_several_servers(self, db_session, web01):
        _server(db_session, "srv-2", name="db01")
        admin = _admin(db_session)
        db_session.add(NotificationServerMute(user_id=admin.id, server_id="srv-1", until=_at(60)))
        db_session.commit()

        ingest(db_session, _heartbeats(["srv-1", "srv-2"]), now=_at(0))

        assert _rows(db_session, admin)[0].read_at is None


# --- bundles --------------------------------------------------------------------


class TestBundles:
    @pytest.fixture()
    def three(self, db_session):
        return [
            _server(db_session, sid, name=name)
            for sid, name in (("srv-1", "web01"), ("srv-2", "db01"), ("srv-3", "mail01"))
        ]

    def test_the_new_keys_of_a_bundle_open_one_bundle_incident(self, db_session, three):
        admin = _admin(db_session)
        ingest(db_session, _heartbeats(["srv-1", "srv-2", "srv-3"]), now=_at(0))

        (incident,) = _incidents(db_session)
        assert (incident.key, incident.source_id, incident.event_count) == (None, None, 1)
        members = (
            db_session.query(NotificationIncidentMember)
            .order_by(NotificationIncidentMember.key)
            .all()
        )
        assert [(m.key, m.server_id) for m in members] == [
            ("hb:srv-1", "srv-1"),
            ("hb:srv-2", "srv-2"),
            ("hb:srv-3", "srv-3"),
        ]
        (row,) = _rows(db_session, admin)
        assert row.title == "Agents not reporting (3)"
        assert _history(db_session, incident) == [
            ("triggered", "srv-1"),
            ("triggered", "srv-2"),
            ("triggered", "srv-3"),
            ("notified", None),
        ]

    def test_a_bundle_folds_what_is_open_and_bundles_the_rest(self, db_session, three):
        _admin(db_session)
        ingest(db_session, _heartbeat("srv-1"), now=_at(0))
        ingest(db_session, _heartbeats(["srv-1", "srv-2", "srv-3"]), now=_at(1))

        single, bundle = _incidents(db_session)
        assert (single.key, single.event_count, single.source_id) == ("hb:srv-1", 2, "srv-1")
        members = db_session.query(NotificationIncidentMember).all()
        assert {(m.incident_id, m.server_id) for m in members} == {
            (bundle.id, "srv-2"),
            (bundle.id, "srv-3"),
        }

    def test_a_bundle_resolves_once_every_member_recovered(self, db_session, three):
        admin = _admin(db_session)
        ingest(db_session, _heartbeats(["srv-1", "srv-2", "srv-3"]), now=_at(0))
        ingest(db_session, _heartbeat("srv-1", "ok"), now=_at(5))

        (incident,) = _incidents(db_session)
        assert incident.state == "open"
        assert _history(db_session, incident)[-1] == ("resolved", "srv-1")
        assert len(_pings(db_session, admin)) == 1

        ingest(
            db_session,
            _heartbeats(["srv-2", "srv-3"], "ok", title="Agents reporting again"),
            now=_at(6),
        )

        (incident,) = _incidents(db_session)
        assert (incident.state, incident.resolved_by) == ("resolved", None)
        (row,) = _rows(db_session, admin)
        assert row.title == "Agents reporting again (3)", "the all-clear covers every member"
        assert row.body == "Heartbeat back\n- web01\n- db01\n- mail01"

    def test_a_bundle_completed_by_a_single_all_clear_names_no_single_server(
        self, db_session, three
    ):
        member = _user(db_session, "member", servers=[three[0]])
        _sub(db_session, member)
        ingest(db_session, _heartbeats(["srv-1", "srv-2", "srv-3"]), now=_at(0))
        ingest(db_session, _heartbeat("srv-1", "ok"), now=_at(1))
        ingest(db_session, _heartbeat("srv-2", "ok"), now=_at(2))
        ingest(db_session, _heartbeat("srv-3", "ok"), now=_at(3))

        (row,) = _rows(db_session, member)
        assert (row.title, row.body) == ("Resolved: Agents not reporting (1)", "- web01")
        assert "mail01" not in row.title + row.body

    def test_a_reader_sees_only_their_servers_of_a_bundle(self, db_session, three):
        member = _user(db_session, "member", servers=[three[0]])
        _sub(db_session, member)
        ingest(db_session, _heartbeats(["srv-1", "srv-2", "srv-3"]), now=_at(0))
        (row,) = _rows(db_session, member)
        assert (row.title, row.body) == ("Agents not reporting (1)", "Heartbeat lost\n- web01")

    def test_a_single_event_does_not_overwrite_the_team_text_of_a_bundle(self, db_session, three):
        _admin(db_session)
        ingest(db_session, _heartbeats(["srv-1", "srv-2", "srv-3"]), now=_at(0))
        ingest(db_session, _heartbeat("srv-1", "ok"), now=_at(1))
        ingest(db_session, _heartbeat("srv-1"), now=_at(2))

        (incident,) = _incidents(db_session)
        assert (incident.title, incident.source_id) == ("Agents not reporting", None)
        assert incident.event_count == 2
        assert _history(db_session, incident)[-1] == ("triggered", "srv-1")
        member = db_session.query(NotificationIncidentMember).filter_by(key="hb:srv-1").one()
        assert member.recovered_at is None

    def test_a_member_key_on_another_server_is_not_the_bundles(self, db_session, three):
        _admin(db_session)
        ingest(db_session, _heartbeats(["srv-1", "srv-2"]), now=_at(0))
        moved = _heartbeat("srv-1").model_copy(update={"source_id": "srv-3"})
        ingest(db_session, moved, now=_at(1))

        bundle, single = _incidents(db_session)
        assert (bundle.event_count, single.key, single.source_id) == (1, "hb:srv-1", "srv-3")

    def test_a_bundle_of_one_server_is_muted_by_its_server(self, db_session, three):
        admin = _admin(db_session)
        db_session.add(NotificationServerMute(user_id=admin.id, server_id="srv-1", until=_at(60)))
        db_session.commit()
        ingest(db_session, _heartbeats(["srv-1", "srv-1"]), now=_at(0))
        assert _rows(db_session, admin)[0].read_at == _at(0)


# --- keyless notices ------------------------------------------------------------


class TestKeyless:
    def test_each_keyless_problem_is_an_incident_of_its_own(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _event(), now=_at(0))
        ingest(db_session, _event(), now=_at(1))

        first, second = _incidents(db_session)
        assert (first.key, second.key) == (None, None)
        assert [r.incident_id for r in _rows(db_session, admin)] == [first.id, second.id]
        assert len(_pings(db_session, admin)) == 2

    def test_a_keyless_problem_nobody_receives_opens_nothing(self, db_session, web01):
        assert ingest(db_session, _event(), now=_at(0)).notified == 0
        assert _incidents(db_session) == []

    def test_info_and_keyless_recoveries_stay_rows_without_an_incident(self, db_session, web01):
        admin = _admin(db_session, min_severity="info")
        ingest(db_session, _event(severity="info"), now=_at(0))
        recovery = _event().model_copy(update={"new_status": "ok"})
        ingest(db_session, recovery, now=_at(1))

        assert [r.incident_id for r in _rows(db_session, admin)] == [None, None]
        assert _incidents(db_session) == []
        assert len(_pings(db_session, admin)) == 2

    def test_a_bundle_without_keys_stays_rows_without_an_incident(self, db_session, web01):
        db01 = _server(db_session, "srv-2", name="db01")
        admin = _admin(db_session)
        reader = _user(db_session, "reader", servers=[db01])
        _sub(db_session, reader)
        bundle = _heartbeats(["srv-1", "srv-2"]).model_copy(update={"incident_keys": None})

        done = ingest(db_session, bundle, now=_at(0))

        assert _incidents(db_session) == []
        assert (done.notified, done.pinged_servers) == (2, ["srv-1", "srv-2"])
        assert [(r.incident_id, r.title) for r in _rows(db_session, reader)] == [
            (None, "Agents not reporting (1)")
        ]
        assert [r.title for r in _rows(db_session, admin)] == ["Agents not reporting (2)"]

    def test_notify_users_opens_an_incident_for_a_warning_only(self, db_session):
        admin = _user(db_session, "boss", is_admin=True, email="boss@example.org")
        assert notify_users(db_session, [admin, admin], _event(severity="warning")) == 1
        assert notify_users(db_session, [admin], _event(severity="info")) == 1

        (incident,) = _incidents(db_session)
        assert [r.incident_id for r in _rows(db_session, admin)] == [incident.id, None]
        assert _pings(db_session, admin) == [], "notify_users never leaves the bell"

    def test_notify_users_without_users_writes_nothing(self, db_session, published):
        assert notify_users(db_session, [], _event(severity="warning")) == 0
        assert (_incidents(db_session), published) == ([], [])


# --- history and retention ------------------------------------------------------


class TestHistory:
    def test_the_history_is_capped_and_keeps_what_people_wrote(self, db_session, web01):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)
        db_session.add(
            NotificationIncidentEvent(
                incident_id=incident.id, at=_at(0), kind="note", actor_id=admin.id, text="on it"
            )
        )
        db_session.commit()

        for i in range(1, HISTORY_MAX + 5):
            ingest(db_session, _check("critical"), now=_at(0) + timedelta(seconds=i))

        history = _history(db_session, incident)
        assert len(history) == HISTORY_MAX
        assert ("note", None) in history
        assert history[0] == ("note", None), "the oldest automatic entries went first"


class TestRetention:
    def test_old_resolved_and_keyless_incidents_go_open_checks_stay(self, db_session, web01):
        admin = _admin(db_session)
        old = datetime.now(timezone.utc) - timedelta(days=100)
        ingest(db_session, _check("critical", key="check:open"), now=old)
        ingest(db_session, _check("critical", key="check:done"), now=old)
        ingest(db_session, _check("ok", key="check:done"), now=old + timedelta(minutes=1))
        ingest(db_session, _event(), now=old)
        ingest(db_session, _check("critical", key="check:new"))
        db_session.add(NotificationServerMute(user_id=admin.id, server_id="srv-1", until=old))
        db_session.commit()

        assert cleanup_old_notifications(db_session, 90) == 2

        assert sorted(i.key for i in _incidents(db_session)) == ["check:new", "check:open"]
        assert len(_rows(db_session, admin)) == 2
        assert db_session.query(NotificationServerMute).count() == 0
        assert db_session.query(NotificationIncidentEvent).count() == 4


# --- the ingress ----------------------------------------------------------------


class TestIngress:
    _PATH = "/api/internal/events"

    def _post(self, test_client, monkeypatch, fired, **fields):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
        monkeypatch.setattr(
            "app.modules.notifications.router.fire_event",
            lambda event_type, event_data: fired.append(event_data["server_id"]),
        )
        payload = {
            "event_type": "monitoring.check.transition",
            "severity": "critical",
            "category": "monitoring",
            "title": "CPU critical on web01",
            "source_type": "server",
            "source_id": "srv-1",
            "new_status": "critical",
            "incident_key": "check:1",
            **fields,
        }
        return test_client.post(self._PATH, headers={"X-Internal-Key": "secret"}, json=payload)

    def test_alert_triggered_fires_only_for_a_ping(self, test_client, db_session, monkeypatch):
        _admin(db_session)
        fired: list = []
        notified = []
        for _ in range(2):
            res = self._post(test_client, monkeypatch, fired)
            assert res.status_code == 202, res.text
            notified.append(res.json()["notified"])

        assert notified == [1, 0]

        assert fired == ["srv-1"], "the repeat folded in silently"
        (incident,) = _incidents(db_session)
        assert (incident.key, incident.event_count) == ("check:1", 2)

    def test_a_bundle_fires_for_the_servers_it_pinged(self, test_client, db_session, monkeypatch):
        fired: list = []
        bundle = {
            "title": "Agents not reporting",
            "source_id": None,
            "incident_key": None,
            "source_ids": ["srv-1", "srv-2"],
            "incident_keys": ["hb:srv-1", "hb:srv-2"],
        }
        self._post(test_client, monkeypatch, fired, **bundle)
        self._post(
            test_client,
            monkeypatch,
            fired,
            **{
                **bundle,
                "source_ids": ["srv-2", "srv-3"],
                "incident_keys": ["hb:srv-2", "hb:srv-3"],
            },
        )
        assert fired == ["srv-1", "srv-2", "srv-3"]

    def test_the_rules_reach_the_incident(self, test_client, db_session, monkeypatch):
        _admin(db_session)
        rules = [{"name": "Ops", "channel": "telegram", "ok": False}]
        assert self._post(test_client, monkeypatch, [], rules=rules).status_code == 202
        assert (
            _incidents(db_session)[0].rules
            == '[{"name": "Ops", "channel": "telegram", "ok": false}]'
        )

    def test_an_invalid_key_is_refused(self, test_client, monkeypatch):
        res = self._post(test_client, monkeypatch, [], incident_key="k" * 201)
        assert res.status_code == 422


class TestIncomingEventKeys:
    _BASE = {
        "event_type": "monitoring.check.transition",
        "severity": "critical",
        "category": "monitoring",
        "title": "Agents not reporting",
        "source_type": "server",
    }

    def _event(self, **fields):
        return IncomingEvent(**{**self._BASE, **fields})

    def test_a_bundle_names_one_key_per_server(self):
        event = self._event(source_ids=["a", "b", "a"], incident_keys=["k:a", "k:b", "k:a"])
        assert event.incident_keys == ["k:a", "k:b", "k:a"]

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ({"source_ids": ["a"], "incident_key": "k:a"}, "not incident_key"),
            ({"source_id": "a", "incident_keys": ["k:a"]}, "same length"),
            ({"source_ids": ["a", "b"], "incident_keys": ["k:a"]}, "same length"),
            ({"source_ids": ["a", "b"], "incident_keys": ["k", "k"]}, "names two servers"),
        ],
    )
    def test_keys_that_do_not_match_the_servers_are_refused(self, fields, message):
        with pytest.raises(ValidationError, match=message):
            self._event(**fields)

    def test_the_bounds(self):
        with pytest.raises(ValidationError):
            self._event(source_id="a", incident_key="")
        with pytest.raises(ValidationError):
            self._event(source_id="a", rules=[{"name": "r", "channel": "email", "ok": True}] * 51)
        with pytest.raises(ValidationError):
            self._event(source_id="a", rules=[{"name": "x" * 201, "channel": "email", "ok": True}])
