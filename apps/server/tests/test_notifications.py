# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Phase A of the notification hub: recipient resolution + ingest, the bell-feed
and preferences API, and the service-to-service event ingress.

The resolver is the security-critical part — least privilege (a user is only
notified about servers they may see) is pinned here."""

import json
from datetime import datetime, timedelta, timezone

from app.core.auth import hash_password
from app.modules.notifications.models import (
    Notification,
    NotificationOutbox,
    NotificationSubscription,
)
from app.modules.notifications.schemas import IncomingEvent
from app.modules.notifications.service import (
    cleanup_old_notifications,
    ingest_event,
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


def _user(db, username, password="passpass123", is_admin=False, servers=None, email=None):
    u = User(
        username=username,
        hashed_password=hash_password(password),
        is_admin=is_admin,
        email=email,
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
