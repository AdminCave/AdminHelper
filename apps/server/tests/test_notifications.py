# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Phase A of the notification hub: recipient resolution + ingest, the bell-feed
and preferences API, and the service-to-service event ingress.

The resolver is the security-critical part — least privilege (a user is only
notified about servers they may see) is pinned here."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.auth import hash_password
from app.modules.notifications import outbox as outbox_mod
from app.modules.notifications import stream_hub
from app.modules.notifications.models import (
    Notification,
    NotificationOutbox,
    NotificationSubscription,
)
from app.modules.notifications.schemas import IncomingEvent
from app.modules.notifications.service import (
    cleanup_old_notifications,
    ingest_event,
    notify_users,
    severity_at_least,
)
from app.modules.servers.models import Server
from app.modules.users.models import User

# --- helpers ---------------------------------------------------------------


def _server(db, sid="srv-1", name="web01", tags=None):
    s = Server(
        id=sid,
        name=name,
        hostname=f"{name}.local",
        tags=json.dumps(tags) if tags is not None else None,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _user(
    db,
    username,
    password="passpass123",
    is_admin=False,
    servers=None,
    email=None,
    telegram_chat_id=None,
):
    u = User(
        username=username,
        hashed_password=hash_password(password),
        is_admin=is_admin,
        email=email,
        telegram_chat_id=telegram_chat_id,
    )
    if servers:
        u.servers = servers
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _sub(
    db,
    user,
    scope_type="all",
    scope_ref=None,
    min_severity="warning",
    email=False,
    telegram=False,
    categories=None,
    enabled=True,
):
    s = NotificationSubscription(
        user_id=user.id,
        scope_type=scope_type,
        scope_ref=scope_ref,
        min_severity=min_severity,
        channel_email=email,
        channel_telegram=telegram,
        categories=json.dumps(categories) if categories else None,
        enabled=enabled,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _event(
    severity="critical",
    category="monitoring",
    source_id="srv-1",
    event_type="monitoring.check.transition",
    title="CPU critical",
):
    return IncomingEvent(
        event_type=event_type,
        severity=severity,
        category=category,
        title=title,
        source_type="server" if source_id else None,
        source_id=source_id,
    )


def _count(db, user):
    return db.query(Notification).filter(Notification.user_id == user.id).count()


def _login(client, username, password="passpass123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- severity helper -------------------------------------------------------


class TestSeverity:
    def test_at_or_above_threshold(self):
        assert severity_at_least("critical", "warning") is True
        assert severity_at_least("warning", "warning") is True
        assert severity_at_least("critical", "info") is True

    def test_below_threshold(self):
        assert severity_at_least("info", "warning") is False
        assert severity_at_least("warning", "critical") is False

    def test_unknown_severity_fails_toward_delivery(self):
        # An unexpected event label must never silently drop an alert.
        assert severity_at_least("emergency", "critical") is True


# --- resolver / ingest matrix ----------------------------------------------


class TestResolver:
    def test_scope_all_admin_gets_server_event(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        _server(db_session, "srv-1")
        assert ingest_event(db_session, _event()) == 1
        assert _count(db_session, admin) == 1

    def test_scope_all_normal_user_needs_assignment(self, db_session):
        srv = _server(db_session, "srv-1")
        # Not assigned to srv-1 → least privilege: no notification.
        outsider = _user(db_session, "outsider")
        _sub(db_session, outsider, scope_type="all")
        assert ingest_event(db_session, _event()) == 0
        assert _count(db_session, outsider) == 0

        # Same subscription, but assigned → notified.
        member = _user(db_session, "member", servers=[srv])
        _sub(db_session, member, scope_type="all")
        assert ingest_event(db_session, _event()) == 1
        assert _count(db_session, member) == 1

    def test_scope_server_matches_only_its_server(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="server", scope_ref="srv-1")
        _server(db_session, "srv-1")
        _server(db_session, "srv-2", name="db01")
        assert ingest_event(db_session, _event(source_id="srv-2")) == 0
        assert ingest_event(db_session, _event(source_id="srv-1")) == 1

    def test_scope_tag_matches_tagged_server(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="tag", scope_ref="prod")
        _server(db_session, "srv-1", tags=["prod", "eu"])
        _server(db_session, "srv-2", name="db01", tags=["dev"])
        assert ingest_event(db_session, _event(source_id="srv-2")) == 0
        assert ingest_event(db_session, _event(source_id="srv-1")) == 1

    def test_min_severity_threshold(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all", min_severity="critical")
        _server(db_session, "srv-1")
        assert ingest_event(db_session, _event(severity="warning")) == 0
        assert ingest_event(db_session, _event(severity="critical")) == 1

    def test_disabled_subscription_is_skipped(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all", enabled=False)
        _server(db_session, "srv-1")
        assert ingest_event(db_session, _event()) == 0

    def test_category_filter(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all", categories=["pki"])
        _server(db_session, "srv-1")
        assert ingest_event(db_session, _event(category="monitoring")) == 0
        assert ingest_event(db_session, _event(category="pki")) == 1

    def test_email_outbox_only_when_address_present(self, db_session):
        _server(db_session, "srv-1")
        no_addr = _user(db_session, "noaddr", is_admin=True, email=None)
        _sub(db_session, no_addr, scope_type="all", email=True)
        ingest_event(db_session, _event())
        assert db_session.query(NotificationOutbox).count() == 0  # feed only, no dead row

        with_addr = _user(db_session, "withaddr", is_admin=True, email="a@b.de")
        _sub(db_session, with_addr, scope_type="all", email=True)
        ingest_event(db_session, _event())
        rows = (
            db_session.query(NotificationOutbox)
            .filter(NotificationOutbox.user_id == with_addr.id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].channel == "email"
        assert rows[0].address == "a@b.de"
        assert rows[0].status == "pending"

    def test_multiple_subscriptions_collapse_and_union_channels(self, db_session):
        srv = _server(db_session, "srv-1")
        user = _user(db_session, "multi", servers=[srv], email="m@x.de")
        _sub(db_session, user, scope_type="all", email=False)
        _sub(db_session, user, scope_type="server", scope_ref="srv-1", email=True)
        assert ingest_event(db_session, _event()) == 1
        # one feed row...
        assert _count(db_session, user) == 1
        # ...but the union of channels queued one e-mail.
        assert db_session.query(NotificationOutbox).filter_by(user_id=user.id).count() == 1

    def test_global_event_is_admin_only(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        srv = _server(db_session, "srv-1")
        normal = _user(db_session, "member", servers=[srv])
        _sub(db_session, normal, scope_type="all")
        # No source_id → security/lifecycle-style global event.
        assert ingest_event(db_session, _event(source_id=None, category="security")) == 1
        assert _count(db_session, admin) == 1
        assert _count(db_session, normal) == 0

    def test_unknown_server_does_not_leak_to_unassigned(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        normal = _user(db_session, "member")
        _sub(db_session, normal, scope_type="all")
        # source_id points at a server that does not exist → treated as global.
        assert ingest_event(db_session, _event(source_id="ghost")) == 1
        assert _count(db_session, admin) == 1
        assert _count(db_session, normal) == 0


# --- bundled events (source_ids) --------------------------------------------


def _bundle(source_ids, severity="critical", category="monitoring", body="Heartbeat lost"):
    return IncomingEvent(
        event_type="monitoring.check.transition",
        severity=severity,
        category=category,
        title="Agents not reporting",
        body=body,
        source_type="server",
        source_ids=source_ids,
        new_status="critical",
    )


def _rows(db, user):
    return db.query(Notification).filter(Notification.user_id == user.id).all()


class TestBundleResolver:
    """monitoring-alert-quality T9: a bundled event names several servers. Each
    user gets one row about exactly the servers they may see and subscribe to —
    title count and lines are per user, so nobody learns of a foreign server."""

    def _three(self, db):
        return (
            _server(db, "srv-1", name="web01", tags=["prod"]),
            _server(db, "srv-2", name="db01", tags=["prod"]),
            _server(db, "srv-3", name="mail01", tags=["dev"]),
        )

    def test_admin_gets_one_row_listing_all_three(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2", "srv-3"])) == 1
        [row] = _rows(db_session, admin)
        assert row.title == "Agents not reporting (3)"
        assert row.body == "Heartbeat lost\n- web01\n- db01\n- mail01"
        assert row.source_type == "server"
        assert row.source_id is None

    def test_assigned_user_sees_only_their_servers(self, db_session):
        srv1, srv2, _ = self._three(db_session)
        member = _user(db_session, "member", servers=[srv1, srv2])
        _sub(db_session, member, scope_type="all")
        outsider = _user(db_session, "outsider")
        _sub(db_session, outsider, scope_type="all")
        assert ingest_event(db_session, _bundle(["srv-3", "srv-2", "srv-1"])) == 1
        [row] = _rows(db_session, member)
        assert row.title == "Agents not reporting (2)"
        # Event order, and no trace of mail01.
        assert row.body == "Heartbeat lost\n- db01\n- web01"
        assert _count(db_session, outsider) == 0

    def test_tag_scope_counts_only_tagged_servers(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="tag", scope_ref="prod")
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2", "srv-3"])) == 1
        [row] = _rows(db_session, admin)
        assert row.title == "Agents not reporting (2)"
        assert row.body == "Heartbeat lost\n- web01\n- db01"

    def test_server_scope_counts_only_its_server(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="server", scope_ref="srv-3")
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2", "srv-3"])) == 1
        [row] = _rows(db_session, admin)
        assert row.title == "Agents not reporting (1)"
        assert row.body == "Heartbeat lost\n- mail01"

    def test_no_scope_hit_means_no_row(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="server", scope_ref="srv-9")
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2", "srv-3"])) == 0
        assert _count(db_session, admin) == 0

    def test_subscriptions_of_one_user_merge_into_one_row(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="server", scope_ref="srv-3")
        _sub(db_session, admin, scope_type="server", scope_ref="srv-1")
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2", "srv-3"])) == 1
        [row] = _rows(db_session, admin)
        assert row.title == "Agents not reporting (2)"
        assert row.body == "Heartbeat lost\n- web01\n- mail01"

    def test_unknown_id_is_listed_for_admins_only(self, db_session):
        srv1, _, _ = self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        member = _user(db_session, "member", servers=[srv1])
        _sub(db_session, member, scope_type="all")
        assert ingest_event(db_session, _bundle(["srv-1", "ghost"])) == 2
        [admin_row] = _rows(db_session, admin)
        assert admin_row.title == "Agents not reporting (2)"
        assert admin_row.body == "Heartbeat lost\n- web01\n- ghost"
        [member_row] = _rows(db_session, member)
        assert member_row.title == "Agents not reporting (1)"
        assert member_row.body == "Heartbeat lost\n- web01"

    def test_only_unknown_ids_reach_no_plain_user(self, db_session):
        member = _user(db_session, "member", servers=[_server(db_session, "srv-1")])
        _sub(db_session, member, scope_type="all")
        assert ingest_event(db_session, _bundle(["ghost-1", "ghost-2"])) == 0

    def test_min_severity_threshold(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all", min_severity="critical")
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2"], severity="warning")) == 0
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2"], severity="critical")) == 1

    def test_category_filter(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all", categories=["pki"])
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2"], category="monitoring")) == 0
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2"], category="pki")) == 1

    def test_one_mail_per_user(self, db_session):
        srv1, srv2, srv3 = self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True, email="a@b.de")
        _sub(db_session, admin, scope_type="all", email=True)
        member = _user(db_session, "member", servers=[srv1, srv2, srv3], email="m@x.de")
        _sub(db_session, member, scope_type="all", email=True)
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2", "srv-3"])) == 2
        for user, address in ((admin, "a@b.de"), (member, "m@x.de")):
            rows = db_session.query(NotificationOutbox).filter_by(user_id=user.id).all()
            assert [(r.channel, r.address) for r in rows] == [("email", address)]

    def test_without_body_the_lines_are_the_text(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        ingest_event(db_session, _bundle(["srv-1", "srv-2"], body=None))
        [row] = _rows(db_session, admin)
        assert row.body == "- web01\n- db01"

    def test_a_repeated_id_counts_once(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        ingest_event(db_session, _bundle(["srv-1", "srv-2", "srv-1"]))
        [row] = _rows(db_session, admin)
        assert row.title == "Agents not reporting (2)"
        assert row.body == "Heartbeat lost\n- web01\n- db01"


def _outbox_rows(db, user):
    rows = (
        db.query(NotificationOutbox)
        .filter(NotificationOutbox.user_id == user.id)
        .order_by(NotificationOutbox.channel)
        .all()
    )
    return [(r.channel, r.address, r.title, r.body) for r in rows]


class TestBundleChannels:
    """monitoring-alert-quality T18: an external channel of a bundled event names
    only the servers of the subscriptions that asked for that channel. A rule
    that sends one server to a customer's Telegram chat must not carry the names
    of the servers another rule only wanted in the bell."""

    def _three(self, db):
        return (
            _server(db, "srv-1", name="web01", tags=["prod"]),
            _server(db, "srv-2", name="db01", tags=["prod"]),
            _server(db, "srv-3", name="mail01", tags=["dev"]),
        )

    def test_telegram_names_only_the_server_of_its_subscription(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True, telegram_chat_id="4711")
        _sub(db_session, admin, scope_type="all")
        _sub(db_session, admin, scope_type="server", scope_ref="srv-2", telegram=True)
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2", "srv-3"])) == 1
        [row] = _rows(db_session, admin)
        assert row.title == "Agents not reporting (3)"
        assert row.body == "Heartbeat lost\n- web01\n- db01\n- mail01"
        assert _outbox_rows(db_session, admin) == [
            ("telegram", "4711", "Agents not reporting (1)", "Heartbeat lost\n- db01")
        ]

    def test_email_names_only_the_server_of_its_subscription(self, db_session, monkeypatch):
        sent = []
        monkeypatch.setattr(
            outbox_mod, "send_email", lambda to, subj, body: sent.append((to, subj, body))
        )
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True, email="a@b.de")
        _sub(db_session, admin, scope_type="all")
        _sub(db_session, admin, scope_type="server", scope_ref="srv-2", email=True)
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2", "srv-3"])) == 1
        [row] = _rows(db_session, admin)
        assert row.title == "Agents not reporting (3)"
        assert _outbox_rows(db_session, admin) == [
            ("email", "a@b.de", "Agents not reporting (1)", "Heartbeat lost\n- db01")
        ]
        # The drain sends the entry's own text, not the bell row's three servers.
        assert outbox_mod.drain_outbox(db_session) == (1, 0)
        assert sent == [("a@b.de", "Agents not reporting (1)", "Heartbeat lost\n- db01")]

    def test_each_channel_names_the_servers_of_its_own_subscriptions(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True, email="a@b.de", telegram_chat_id="4711")
        _sub(db_session, admin, scope_type="tag", scope_ref="prod", email=True)
        _sub(db_session, admin, scope_type="server", scope_ref="srv-3", telegram=True)
        assert ingest_event(db_session, _bundle(["srv-1", "srv-2", "srv-3"])) == 1
        [row] = _rows(db_session, admin)
        assert row.title == "Agents not reporting (3)"
        assert _outbox_rows(db_session, admin) == [
            ("email", "a@b.de", "Agents not reporting (2)", "Heartbeat lost\n- web01\n- db01"),
            ("telegram", "4711", "Agents not reporting (1)", "Heartbeat lost\n- mail01"),
        ]

    def test_a_channel_without_a_server_gets_no_entry(self, db_session):
        srv1, srv2, _ = self._three(db_session)
        member = _user(
            db_session, "member", servers=[srv1, srv2], email="m@x.de", telegram_chat_id="4711"
        )
        _sub(db_session, member, scope_type="all")
        # Not in the bundle, a server the member may not see, a level the bundle
        # does not reach: none of these routes a server to its channel.
        _sub(db_session, member, scope_type="server", scope_ref="srv-9", email=True)
        _sub(db_session, member, scope_type="server", scope_ref="srv-3", telegram=True)
        _sub(db_session, member, scope_type="all", min_severity="critical", telegram=True)
        bundle = _bundle(["srv-1", "srv-2", "srv-3"], severity="warning")
        assert ingest_event(db_session, bundle) == 1
        [row] = _rows(db_session, member)
        assert row.title == "Agents not reporting (2)"
        assert _outbox_rows(db_session, member) == []

    def test_without_body_the_channel_lines_are_the_text(self, db_session):
        self._three(db_session)
        admin = _user(db_session, "boss", is_admin=True, telegram_chat_id="4711")
        _sub(db_session, admin, scope_type="all")
        _sub(db_session, admin, scope_type="server", scope_ref="srv-1", telegram=True)
        ingest_event(db_session, _bundle(["srv-1", "srv-2"], body=None))
        assert _outbox_rows(db_session, admin) == [
            ("telegram", "4711", "Agents not reporting (1)", "- web01")
        ]

    def test_a_single_event_queues_entries_without_text_of_their_own(self, db_session):
        _server(db_session, "srv-1")
        admin = _user(db_session, "boss", is_admin=True, email="a@b.de", telegram_chat_id="4711")
        _sub(db_session, admin, scope_type="all")
        _sub(db_session, admin, scope_type="server", scope_ref="srv-1", email=True, telegram=True)
        assert ingest_event(db_session, _event()) == 1
        assert _outbox_rows(db_session, admin) == [
            ("email", "a@b.de", None, None),
            ("telegram", "4711", None, None),
        ]


# --- direct delivery to chosen users ---------------------------------------


class TestNotifyUsers:
    """notify_users skips the subscription resolver: the caller has already
    chosen the recipients, and only the bell is written."""

    def _direct_event(self):
        return _event(
            severity="info",
            category="lifecycle",
            source_id=None,
            event_type="test.direct",
            title="direct notice",
        )

    def test_exactly_the_given_users_get_a_row(self, db_session):
        # Neither recipient has a subscription and the member is assigned to no
        # server, so ingest_event would reach neither of them.
        admin = _user(db_session, "boss", is_admin=True)
        member = _user(db_session, "member")
        bystander = _user(db_session, "bystander", is_admin=True)
        _sub(db_session, bystander, scope_type="all", min_severity="info")

        assert notify_users(db_session, [admin, member], self._direct_event()) == 2

        assert _count(db_session, admin) == 1
        assert _count(db_session, member) == 1
        assert _count(db_session, bystander) == 0
        row = db_session.query(Notification).filter(Notification.user_id == member.id).one()
        assert (row.severity, row.category, row.event_type, row.title) == (
            "info",
            "lifecycle",
            "test.direct",
            "direct notice",
        )

    def test_a_user_listed_twice_gets_one_row(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        assert notify_users(db_session, [admin, admin], self._direct_event()) == 1
        assert _count(db_session, admin) == 1

    def test_no_outbox_row_even_with_an_external_channel(self, db_session):
        admin = _user(db_session, "boss", is_admin=True, email="a@b.de")
        _sub(db_session, admin, scope_type="all", min_severity="info", email=True)
        notify_users(db_session, [admin], self._direct_event())
        assert _count(db_session, admin) == 1
        assert db_session.query(NotificationOutbox).count() == 0

    def test_empty_list_writes_and_publishes_nothing(self, db_session, monkeypatch):
        calls = []
        monkeypatch.setattr(stream_hub, "publish", lambda *a: calls.append(a))
        _user(db_session, "boss", is_admin=True)
        assert notify_users(db_session, [], self._direct_event()) == 0
        assert db_session.query(Notification).count() == 0
        assert calls == []

    def test_publishes_the_sse_nudge_to_the_given_users(self, db_session, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            stream_hub, "publish", lambda uids, mid: seen.update(uids=list(uids), mid=mid)
        )
        admin = _user(db_session, "boss", is_admin=True)
        member = _user(db_session, "member")
        notify_users(db_session, [admin, member], self._direct_event())
        assert sorted(seen["uids"]) == sorted([admin.id, member.id])
        newest = db_session.query(Notification.id).order_by(Notification.id.desc()).first()
        assert seen["mid"] == newest[0]


# --- bell feed API ---------------------------------------------------------


class TestFeedApi:
    def test_feed_is_own_scope(self, test_client, db_session):
        alice = _user(db_session, "alice", is_admin=True)
        bob = _user(db_session, "bob", is_admin=True)
        _server(db_session, "srv-1")
        _sub(db_session, alice, scope_type="all")
        _sub(db_session, bob, scope_type="all")
        ingest_event(db_session, _event(title="for both"))

        res = test_client.get("/api/notifications", headers=_login(test_client, "alice"))
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body) == 1
        assert body[0]["title"] == "for both"
        assert body[0]["read"] is False

    def test_unread_count_and_mark_read(self, test_client, db_session):
        alice = _user(db_session, "alice", is_admin=True)
        _server(db_session, "srv-1")
        _sub(db_session, alice, scope_type="all")
        ingest_event(db_session, _event())
        ingest_event(db_session, _event(severity="warning", title="second"))
        headers = _login(test_client, "alice")

        assert test_client.get("/api/notifications/unread-count", headers=headers).json() == {
            "count": 2
        }
        upd = test_client.post("/api/notifications/read", headers=headers, json={})
        assert upd.json() == {"updated": 2}
        assert test_client.get("/api/notifications/unread-count", headers=headers).json() == {
            "count": 0
        }

    def test_mark_read_specific_ids(self, test_client, db_session):
        alice = _user(db_session, "alice", is_admin=True)
        _server(db_session, "srv-1")
        _sub(db_session, alice, scope_type="all")
        ingest_event(db_session, _event())
        ingest_event(db_session, _event(title="second"))
        headers = _login(test_client, "alice")

        ids = [n["id"] for n in test_client.get("/api/notifications", headers=headers).json()]
        res = test_client.post("/api/notifications/read", headers=headers, json={"ids": [ids[0]]})
        assert res.json() == {"updated": 1}
        assert (
            test_client.get("/api/notifications/unread-count", headers=headers).json()["count"] == 1
        )

    def test_feed_requires_auth(self, test_client):
        assert test_client.get("/api/notifications").status_code == 401

    def test_timestamps_are_utc_with_z_under_a_non_utc_session(self, test_client, db_session):
        # timestamptz comes back in the session zone; the API writes the same instant
        # in UTC with Z (R-0064), whatever zone the connection runs in.
        db_session.execute(text("SET LOCAL TIME ZONE 'Europe/Berlin'"))
        alice = _user(db_session, "alice", is_admin=True)
        row = Notification(
            user_id=alice.id,
            created_at=datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc),
            read_at=datetime(2026, 10, 5, 12, 30, 0, tzinfo=timezone.utc),
            severity="info",
            category="lifecycle",
            event_type="tz.probe",
            title="tz",
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        assert row.created_at.utcoffset() == timedelta(hours=2)  # the premise: not UTC

        res = test_client.get("/api/notifications", headers=_login(test_client, "alice"))
        assert res.status_code == 200, res.text
        got = [(n["createdAt"], n["readAt"]) for n in res.json() if n["title"] == "tz"]
        assert got == [("2026-10-05T12:00:00Z", "2026-10-05T12:30:00Z")]


# --- preferences API -------------------------------------------------------


class TestPrefsApi:
    def test_get_empty_prefs(self, test_client, db_session):
        _user(db_session, "alice")
        res = test_client.get(
            "/api/users/me/notification-prefs", headers=_login(test_client, "alice")
        )
        assert res.status_code == 200
        assert res.json() == {"email": None, "telegramChatId": None, "subscriptions": []}

    def test_put_then_get_roundtrip(self, test_client, db_session):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        payload = {
            "email": "alice@example.com",
            "subscriptions": [
                {"scope_type": "all", "min_severity": "warning", "channel_email": True},
                {"scope_type": "tag", "scope_ref": "prod", "min_severity": "critical"},
            ],
        }
        put = test_client.put("/api/users/me/notification-prefs", headers=headers, json=payload)
        assert put.status_code == 200, put.text
        got = test_client.get("/api/users/me/notification-prefs", headers=headers).json()
        assert got["email"] == "alice@example.com"
        assert len(got["subscriptions"]) == 2
        assert got["subscriptions"][0]["channelEmail"] is True

    def test_put_replaces_all(self, test_client, db_session):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        first = {
            "subscriptions": [{"scope_type": "all"}, {"scope_type": "server", "scope_ref": "x"}]
        }
        test_client.put("/api/users/me/notification-prefs", headers=headers, json=first)
        second = {"subscriptions": [{"scope_type": "all", "channel_email": True}]}
        test_client.put("/api/users/me/notification-prefs", headers=headers, json=second)
        got = test_client.get("/api/users/me/notification-prefs", headers=headers).json()
        assert len(got["subscriptions"]) == 1
        assert got["subscriptions"][0]["channelEmail"] is True

    def test_tag_scope_requires_ref(self, test_client, db_session):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        bad = {"subscriptions": [{"scope_type": "tag"}]}
        assert (
            test_client.put(
                "/api/users/me/notification-prefs", headers=headers, json=bad
            ).status_code
            == 422
        )

    def test_invalid_email_rejected(self, test_client, db_session):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        bad = {"email": "not-an-email", "subscriptions": []}
        assert (
            test_client.put(
                "/api/users/me/notification-prefs", headers=headers, json=bad
            ).status_code
            == 422
        )


# --- internal event ingress ------------------------------------------------


class TestIngress:
    _PATH = "/api/internal/events"

    def _payload(self):
        return {
            "event_type": "monitoring.check.transition",
            "severity": "critical",
            "category": "monitoring",
            "title": "CPU critical on web01",
            "source_type": "server",
            "source_id": "srv-1",
        }

    def test_missing_key_rejected(self, test_client):
        assert test_client.post(self._PATH, json=self._payload()).status_code == 403

    def test_wrong_key_rejected(self, test_client, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "right-key")
        res = test_client.post(
            self._PATH, headers={"X-Internal-Key": "wrong"}, json=self._payload()
        )
        assert res.status_code == 403

    def test_blank_configured_key_is_fail_closed(self, test_client, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "")
        res = test_client.post(self._PATH, headers={"X-Internal-Key": ""}, json=self._payload())
        assert res.status_code == 403

    def test_non_ascii_key_is_rejected_not_a_500(self, test_client, monkeypatch):
        # code-review-fixes T5 (B4): secrets.compare_digest raises TypeError on
        # str arguments holding non-ASCII, and header values are latin-1 decoded
        # — so one byte above 0x7F turned this gate into an unhandled 500 that an
        # unauthenticated caller could trigger at will. The monitoring side was
        # already hardened (app/core/auth.py::_key_matches); this pins the server.
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
        # Bytes, because httpx refuses a non-ASCII str header outright (that
        # would test the client, not us). httpx transcodes them to UTF-8, so the
        # handler sees a different code point than a real 0xE9 on the wire would
        # deliver — irrelevant here: what matters is that the value reaches
        # compare_digest as a non-ASCII str, which is what made it throw.
        res = test_client.post(
            self._PATH,
            headers={"X-Internal-Key": "sécret".encode("latin-1")},
            json=self._payload(),
        )
        assert res.status_code == 403

    def test_valid_key_fans_out(self, test_client, db_session, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        _server(db_session, "srv-1")
        res = test_client.post(
            self._PATH, headers={"X-Internal-Key": "secret"}, json=self._payload()
        )
        assert res.status_code == 202, res.text
        assert res.json() == {"notified": 1}
        assert _count(db_session, admin) == 1

    def _bundle_payload(self, source_ids):
        payload = {**self._payload(), "source_ids": source_ids}
        del payload["source_id"]
        return payload

    def test_bundle_fans_out_per_user(self, test_client, db_session, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
        srv1 = _server(db_session, "srv-1", name="web01")
        _server(db_session, "srv-2", name="db01")
        member = _user(db_session, "member", servers=[srv1])
        _sub(db_session, member, scope_type="all")
        res = test_client.post(
            self._PATH,
            headers={"X-Internal-Key": "secret"},
            json=self._bundle_payload(["srv-1", "srv-2"]),
        )
        assert res.status_code == 202, res.text
        assert res.json() == {"notified": 1}
        [row] = _rows(db_session, member)
        assert row.title == "CPU critical on web01 (1)"
        assert row.body == "- web01"

    def test_bundle_takes_500_ids(self, test_client, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
        ids = [f"srv-{i}" for i in range(500)]
        ids[0] = "x" * 256
        res = test_client.post(
            self._PATH, headers={"X-Internal-Key": "secret"}, json=self._bundle_payload(ids)
        )
        assert res.status_code == 202, res.text

    def test_bundle_shape_is_bounded(self, test_client, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
        both = {**self._payload(), "source_ids": ["srv-2"]}
        # The error type pins which bound refused it, not just that one did.
        for payload, error in (
            (both, "value_error"),
            (self._bundle_payload([f"srv-{i}" for i in range(501)]), "too_long"),
            (self._bundle_payload([]), "too_short"),
            (self._bundle_payload(["srv-1", "x" * 257]), "string_too_long"),
            (self._bundle_payload([""]), "string_too_short"),
            (self._bundle_payload(["srv-1", ""]), "string_too_short"),
        ):
            res = test_client.post(self._PATH, headers={"X-Internal-Key": "secret"}, json=payload)
            assert res.status_code == 422, f"{error}: {res.status_code} {res.text}"
            assert [d["type"] for d in res.json()["detail"]] == [error], res.text

    def _assert_reserved(self, res, label):
        assert res.status_code == 422, f"{label}: {res.status_code} {res.text}"
        assert [(d["loc"], d["msg"]) for d in res.json()["detail"]] == [
            (["body", "source_type"], "reserved for notices of the server itself")
        ], res.text

    def test_a_source_type_of_the_server_is_refused(self, test_client, db_session, monkeypatch):
        # Under frp_config, frps and certificate_expiry the server keeps notices of its own and finds them
        # again by source_type: a row from the ingress would count as one of them.
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        for source_type in ("frp_config", "frps", "certificate_expiry"):
            for source_id in ("cfg-1:auth_token", None):
                payload = {**self._payload(), "source_type": source_type, "source_id": source_id}
                if source_id is None:
                    del payload["source_id"]
                res = test_client.post(
                    self._PATH, headers={"X-Internal-Key": "secret"}, json=payload
                )
                self._assert_reserved(res, f"{source_type} {source_id}")
        assert db_session.query(Notification).count() == 0

        # Counter-probe: the same admin gets the row of a source type of the ingress.
        res = test_client.post(
            self._PATH, headers={"X-Internal-Key": "secret"}, json=self._payload()
        )
        assert res.status_code == 202, res.text
        assert res.json() == {"notified": 1}
        assert _count(db_session, admin) == 1

    def test_the_refused_source_types_are_those_the_server_writes(
        self, test_client, db_session, monkeypatch
    ):
        # Taken from the writers, not spelled out: a renamed source type on the
        # server's side turns this red instead of reopening the ingress for it.
        import app.main as m
        from app.modules.enrollment import expiry
        from app.modules.frp import supervisor_watch
        from app.modules.frp.models import FrpServerConfig

        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        config = FrpServerConfig(
            id="cfg-short",
            name="frps",
            server_addr="frps.example",
            bind_port=7000,
            auth_token="s" * 15,
        )
        db_session.add(config)
        db_session.commit()
        m._report_rejected_fields(db_session, config)
        [told] = db_session.query(Notification).all()
        assert told.source_id == "cfg-short:auth_token"

        for source_type, source_id in (
            (told.source_type, told.source_id),
            (supervisor_watch.SOURCE_TYPE, "boot-1:1"),
            (expiry.SOURCE_TYPE, f"{'ab' * 32}:critical"),
        ):
            payload = {**self._payload(), "source_type": source_type, "source_id": source_id}
            res = test_client.post(self._PATH, headers={"X-Internal-Key": "secret"}, json=payload)
            self._assert_reserved(res, source_type)
        assert db_session.query(Notification).count() == 1


class TestAlertTriggeredHook:
    """T31: a critical monitoring.check.transition additionally fires the
    documented alert.triggered event hook; anything else does not."""

    _PATH = "/api/internal/events"

    def _post(self, test_client, monkeypatch, fired, **overrides):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
        monkeypatch.setattr(
            "app.modules.notifications.router.fire_event",
            lambda event_type, event_data: fired.append((event_type, event_data)),
        )
        payload = {
            "event_type": "monitoring.check.transition",
            "severity": "critical",
            "category": "monitoring",
            "title": "CPU critical on web01",
            "body": "cpu 99% > 95%",
            "source_type": "server",
            "source_id": "srv-1",
            **overrides,
        }
        return test_client.post(self._PATH, headers={"X-Internal-Key": "secret"}, json=payload)

    def test_critical_transition_fires_alert_triggered(self, test_client, monkeypatch):
        fired: list = []
        assert self._post(test_client, monkeypatch, fired).status_code == 202
        assert fired == [
            (
                "alert.triggered",
                {
                    "server_id": "srv-1",
                    "severity": "critical",
                    "title": "CPU critical on web01",
                    "message": "cpu 99% > 95%",
                },
            )
        ]

    def test_warning_transition_does_not_fire_alert_triggered(self, test_client, monkeypatch):
        fired: list = []
        assert self._post(test_client, monkeypatch, fired, severity="warning").status_code == 202
        assert fired == []

    def test_recovery_does_not_fire_alert_triggered(self, test_client, monkeypatch):
        # T36: critical -> ok arrives with severity critical (worse-of-both);
        # new_status distinguishes the recovery leg from a real alert.
        fired: list = []
        res = self._post(test_client, monkeypatch, fired, new_status="ok")
        assert res.status_code == 202
        assert fired == []

    def test_new_status_critical_fires(self, test_client, monkeypatch):
        fired: list = []
        assert self._post(test_client, monkeypatch, fired, new_status="critical").status_code == 202
        assert len(fired) == 1

    def test_other_critical_event_does_not_fire_alert_triggered(self, test_client, monkeypatch):
        fired: list = []
        res = self._post(test_client, monkeypatch, fired, event_type="pki.cert.expiring")
        assert res.status_code == 202
        assert fired == []

    # monitoring-alert-quality T10: a bundled event (several silent agents)
    # fires the hook once per server — a hook keeps seeing one server per call.

    def _post_bundle(self, test_client, monkeypatch, fired, source_ids, **overrides):
        bundle = {
            "title": "Agents not reporting",
            "body": "Heartbeat lost",
            "source_id": None,
            "source_ids": source_ids,
            "new_status": "critical",
        }
        return self._post(test_client, monkeypatch, fired, **{**bundle, **overrides})

    def _server_ids(self, fired):
        assert {event_type for event_type, _ in fired} <= {"alert.triggered"}
        return [data["server_id"] for _, data in fired]

    def test_bundle_fires_once_per_server(self, test_client, monkeypatch):
        fired: list = []
        res = self._post_bundle(test_client, monkeypatch, fired, ["srv-1", "srv-2", "srv-3"])
        assert res.status_code == 202, res.text
        assert fired == [
            (
                "alert.triggered",
                {
                    "server_id": server_id,
                    "severity": "critical",
                    "title": "Agents not reporting",
                    "message": "Heartbeat lost",
                },
            )
            for server_id in ("srv-1", "srv-2", "srv-3")
        ]

    def test_bundle_repeated_id_fires_once(self, test_client, monkeypatch):
        fired: list = []
        res = self._post_bundle(test_client, monkeypatch, fired, ["srv-2", "srv-1", "srv-2"])
        assert res.status_code == 202, res.text
        assert self._server_ids(fired) == ["srv-2", "srv-1"]

    def test_bundle_recovery_does_not_fire(self, test_client, monkeypatch):
        fired: list = []
        res = self._post_bundle(
            test_client, monkeypatch, fired, ["srv-1", "srv-2", "srv-3"], new_status="ok"
        )
        assert res.status_code == 202, res.text
        assert fired == []

    def test_bundle_with_warning_severity_does_not_fire(self, test_client, monkeypatch):
        fired: list = []
        res = self._post_bundle(
            test_client, monkeypatch, fired, ["srv-1", "srv-2", "srv-3"], severity="warning"
        )
        assert res.status_code == 202, res.text
        assert fired == []


# --- malformed-data tolerance (fail-open, never drop an alert) --------------


class TestResolverTolerance:
    def test_broken_categories_json_does_not_drop(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        db_session.add(
            NotificationSubscription(
                user_id=admin.id,
                scope_type="all",
                min_severity="warning",
                categories="{not valid json",
                channel_email=False,
                channel_telegram=False,
                enabled=True,
            )
        )
        db_session.commit()
        _server(db_session, "srv-1")
        # Malformed filter must fail open, not silently swallow the event.
        assert ingest_event(db_session, _event(category="monitoring")) == 1

    def test_broken_server_tags_json_does_not_crash(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        db_session.add(Server(id="srv-1", name="x", hostname="x.local", tags="{not json"))
        db_session.commit()
        assert ingest_event(db_session, _event()) == 1


# --- bell-feed retention ----------------------------------------------------


class TestRetention:
    def test_cleanup_removes_only_old_rows(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        old = Notification(
            user_id=admin.id,
            severity="info",
            category="monitoring",
            event_type="x",
            title="old",
            created_at=datetime.now(timezone.utc) - timedelta(days=100),
        )
        recent = Notification(
            user_id=admin.id,
            severity="info",
            category="monitoring",
            event_type="x",
            title="recent",
        )
        db_session.add_all([old, recent])
        db_session.commit()

        assert cleanup_old_notifications(db_session, 90) == 1
        assert _count(db_session, admin) == 1

    def test_cleanup_zero_keeps_everything(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _server(db_session, "srv-1")
        _sub(db_session, admin, scope_type="all")
        ingest_event(db_session, _event())
        assert cleanup_old_notifications(db_session, 0) == 0
        assert _count(db_session, admin) == 1
