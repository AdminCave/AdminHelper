# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Phase B2: the in-process event bus feeds notification-worthy events into the
hub. build_event holds the pure mapping; _run_event wires the bridge in."""

from app.modules.notifications.event_bridge import build_event
from app.modules.notifications.service import ingest_event

from .test_notifications import _count, _server, _sub, _user


class TestBuildEvent:
    def test_user_created_admin_is_security_event(self):
        ev = build_event("user.created", {"id": 7, "username": "root2", "is_admin": True})
        assert ev is not None
        assert ev.category == "security"
        assert ev.severity == "warning"
        assert ev.source_id is None  # global → admin-only fan-out
        assert "root2" in ev.title

    def test_user_created_nonadmin_is_ignored(self):
        assert build_event("user.created", {"id": 8, "username": "joe", "is_admin": False}) is None

    def test_user_promoted_is_security_event(self):
        ev = build_event("user.promoted", {"id": 9, "username": "promo"})
        assert ev is not None
        assert ev.event_type == "security.admin.promoted"
        assert ev.category == "security"
        assert ev.severity == "warning"
        assert ev.source_id is None  # global → admin-only fan-out
        assert "promo" in ev.title

    def test_server_deleted_is_lifecycle_global(self):
        ev = build_event("server.deleted", {"id": "srv-1", "name": "web01"})
        assert ev is not None
        assert ev.category == "lifecycle"
        assert ev.source_id is None
        assert "web01" in ev.title

    def test_tunnel_created_is_server_scoped(self):
        ev = build_event("frp.tunnel.created", {"id": "t1", "name": "ssh", "serverId": "srv-1"})
        assert ev is not None
        assert ev.category == "lifecycle"
        assert ev.severity == "info"
        assert ev.source_id == "srv-1"

    def test_tunnel_created_without_server_is_global(self):
        ev = build_event("frp.tunnel.created", {"id": "t1", "name": "ssh"})
        assert ev is not None
        assert ev.source_id is None

    def test_unmapped_event_is_ignored(self):
        assert build_event("connection.updated", {"id": "c1"}) is None
        assert build_event("server.startup", {}) is None


class TestBridgeDelivers:
    def test_admin_created_reaches_admins(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all", categories=["security"])
        ev = build_event("user.created", {"id": 5, "username": "newadmin", "is_admin": True})
        ingest_event(db_session, ev)
        assert _count(db_session, admin) == 1

    def test_admin_promoted_reaches_admins(self, db_session):
        admin = _user(db_session, "boss", is_admin=True)
        _sub(db_session, admin, scope_type="all", categories=["security"])
        ev = build_event("user.promoted", {"id": 6, "username": "promo"})
        ingest_event(db_session, ev)
        assert _count(db_session, admin) == 1

    def test_tunnel_created_reaches_assigned_user(self, db_session):
        srv = _server(db_session, "srv-1")
        member = _user(db_session, "member", servers=[srv])
        _sub(db_session, member, scope_type="server", scope_ref="srv-1", min_severity="info")
        ev = build_event("frp.tunnel.created", {"id": "t1", "name": "ssh", "serverId": "srv-1"})
        ingest_event(db_session, ev)
        assert _count(db_session, member) == 1


class TestWiring:
    def test_run_event_invokes_bridge(self, db_session, monkeypatch):
        from sqlalchemy.orm import sessionmaker

        import app.core.database as database
        import app.core.events as events

        seen = {}
        monkeypatch.setattr(
            "app.modules.notifications.event_bridge.handle_event",
            lambda et, ed: seen.update(et=et, ed=ed),
        )
        # _run_event opens its own SessionLocal; bind it to the test connection.
        monkeypatch.setattr(
            database, "SessionLocal", sessionmaker(bind=db_session.connection(), autoflush=False)
        )
        events._run_event("server.deleted", {"id": "s1", "name": "web01"})
        assert seen.get("et") == "server.deleted"
        assert seen.get("ed") == {"id": "s1", "name": "web01"}
