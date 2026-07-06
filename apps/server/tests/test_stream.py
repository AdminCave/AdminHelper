# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Phase S: the SSE push pipeline — per-worker registry, the ingest publish hook,
and the stream endpoint's auth gate. The Redis fan-out and the live frame
delivery are covered by the end-to-end test, not here."""

import pytest

from app.modules.notifications import stream_hub
from app.modules.notifications.service import ingest_event

from .test_notifications import _event, _server, _sub, _user


@pytest.fixture(autouse=True)
def _clean_hub():
    stream_hub._subscribers.clear()
    yield
    stream_hub._subscribers.clear()


class TestStreamHubRegistry:
    def test_register_deliver_unregister(self):
        q = stream_hub.register(1)
        stream_hub.deliver_local(1, "payload")
        assert q.get_nowait() == "payload"
        stream_hub.unregister(1, q)
        stream_hub.deliver_local(1, "ignored")  # no registered queue anymore
        assert q.empty()

    def test_deliver_targets_only_that_user(self):
        q1 = stream_hub.register(1)
        q2 = stream_hub.register(2)
        stream_hub.deliver_local(1, "for-1")
        assert q1.get_nowait() == "for-1"
        assert q2.empty()

    def test_multiple_streams_per_user_all_get_it(self):
        a = stream_hub.register(1)
        b = stream_hub.register(1)
        stream_hub.deliver_local(1, "x")
        assert a.get_nowait() == "x"
        assert b.get_nowait() == "x"

    def test_queue_overflow_drops_without_error(self):
        q = stream_hub.register(1)
        for i in range(40):  # maxsize is 32
            stream_hub.deliver_local(1, str(i))
        assert q.qsize() <= 32


class TestPublishHook:
    def test_ingest_publishes_to_recipients(self, db_session, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            stream_hub, "publish", lambda uids, mid: seen.update(uids=list(uids), mid=mid)
        )
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all")
        _server(db_session, "srv-1")
        ingest_event(db_session, _event())
        assert seen["uids"] == [admin.id]
        assert seen["mid"] > 0

    def test_no_publish_without_recipients(self, db_session, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr(
            stream_hub, "publish", lambda *a: calls.__setitem__("n", calls["n"] + 1)
        )
        _server(db_session, "srv-1")  # no subscriptions → nobody notified
        ingest_event(db_session, _event())
        assert calls["n"] == 0

    def test_publish_reuses_the_redis_client(self, monkeypatch):
        # 5.32: the fan-out publish reuses one process-wide client instead of a fresh from_url + TCP
        # connect per notification.
        import redis

        import app.core.config as cfg

        calls = {"from_url": 0}
        published = []

        class _FakeClient:
            def publish(self, channel, payload):
                published.append(payload)

        def _fake_from_url(url, **kw):
            calls["from_url"] += 1
            return _FakeClient()

        monkeypatch.setattr(cfg, "REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setattr(redis.Redis, "from_url", staticmethod(_fake_from_url))
        monkeypatch.setattr(stream_hub, "_pub_client", None)

        stream_hub.publish([1], 10)
        stream_hub.publish([2], 11)
        stream_hub.publish([3], 12)

        assert calls["from_url"] == 1, "from_url should run once, not per publish"
        assert len(published) == 3


class TestStreamAuth:
    def test_stream_requires_auth(self, test_client):
        # No bearer token → 401 before the stream ever opens.
        assert test_client.get("/api/notifications/stream").status_code == 401


class TestStreamReauth:
    """3.38: a live stream re-validates the JWT + mTLS revocation each cycle, so a
    logout (JWT blacklist) or a revoke reaches an already-open stream instead of
    pushing nudges forever."""

    @staticmethod
    def _patch(monkeypatch, *, user, revoked):
        import app.core.auth as auth_mod
        import app.core.database as db_mod
        import app.core.identity as id_mod

        class _FakeDB:
            def close(self):
                pass

        monkeypatch.setattr(db_mod, "SessionLocal", lambda: _FakeDB())
        monkeypatch.setattr(auth_mod, "_get_user_from_token", lambda token, db: user)
        monkeypatch.setattr(id_mod, "_is_revoked", lambda db, cn, scope: revoked)

    def test_ok_when_valid_and_not_revoked(self, monkeypatch):
        from app.modules.notifications.stream import _stream_reauth_ok

        self._patch(monkeypatch, user=object(), revoked=False)
        assert _stream_reauth_ok("tok", "cn", "access", True) is True

    def test_ends_when_jwt_blacklisted(self, monkeypatch):
        from app.modules.notifications.stream import _stream_reauth_ok

        self._patch(monkeypatch, user=None, revoked=False)  # logout / blacklist
        assert _stream_reauth_ok("tok", "cn", "access", True) is False

    def test_ends_when_identity_revoked(self, monkeypatch):
        from app.modules.notifications.stream import _stream_reauth_ok

        self._patch(monkeypatch, user=object(), revoked=True)
        assert _stream_reauth_ok("tok", "cn", "access", True) is False

    def test_unverified_identity_skips_revocation_check(self, monkeypatch):
        from app.modules.notifications.stream import _stream_reauth_ok

        # Permissive rollout: no verified cert -> only the JWT gates, the (would-be)
        # revoked flag must not end the stream.
        self._patch(monkeypatch, user=object(), revoked=True)
        assert _stream_reauth_ok("tok", None, None, False) is True
