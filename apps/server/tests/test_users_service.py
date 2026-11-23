# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-0690: every way a user comes into being runs through users.service.create_user,
so each fires one user.created, writes one audit row and syncs the FRP policy."""

import secrets
from concurrent.futures import Future

import pytest

from app.cli import create_admin
from app.core import events
from app.core.auth import hash_api_key
from app.core.config import BOOTSTRAP_SETUP_FILE, BOOTSTRAP_TOKEN_FILE
from app.core.request_context import Actor
from app.modules.audit.models import AuditLog
from app.modules.users import service as users_service
from app.modules.users.models import User


class _RecordingExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, /, *args, **kwargs):
        self.calls.append(args)
        future = Future()
        future.set_result(None)
        return future


@pytest.fixture()
def fired(monkeypatch):
    recorder = _RecordingExecutor()
    monkeypatch.setattr(events, "_executor", recorder)
    return recorder.calls


@pytest.fixture()
def synced(monkeypatch):
    calls = []

    def _sync(db):
        calls.append(sorted(u.username for u in db.query(User).all()))
        return True

    monkeypatch.setattr(users_service, "sync_policy", _sync)
    return calls


def _created(fired, username):
    return [data for name, data in fired if name == "user.created" and data["username"] == username]


def _audit(db, username):
    return db.query(AuditLog).filter(AuditLog.object_label == username).all()


def test_api_create(test_client, db_session, admin_user, fired, synced):
    login = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    res = test_client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"username": "alice", "password": "alicepass1"},
    )
    assert res.status_code == 201, res.text
    user = db_session.query(User).filter_by(username="alice").one()
    assert _created(fired, "alice") == [{"id": user.id, "username": "alice", "is_admin": False}]
    rows = _audit(db_session, "alice")
    assert [(r.action, r.actor_label) for r in rows] == [("user.created", "admin")]
    assert synced == [["admin", "alice"]]


def test_bootstrap(test_client, db_session, fired, synced):
    raw = secrets.token_urlsafe(32)
    BOOTSTRAP_TOKEN_FILE.write_text(hash_api_key(raw))
    try:
        res = test_client.post(
            "/api/auth/bootstrap",
            json={"token": raw, "username": "first", "password": "abcdefgh"},
        )
    finally:
        BOOTSTRAP_TOKEN_FILE.unlink(missing_ok=True)
    assert res.status_code == 201, res.text
    user = db_session.query(User).filter_by(username="first").one()
    assert _created(fired, "first") == [{"id": user.id, "username": "first", "is_admin": True}]
    rows = _audit(db_session, "first")
    # The bootstrap admin is its own actor, under the action filters already know.
    assert [(r.action, r.actor_type, r.actor_id) for r in rows] == [
        ("auth.bootstrap", "user", str(user.id))
    ]
    assert synced == [["first"]]


def test_cli_create_admin(db_session, fired, synced):
    assert create_admin(db_session, "kevin", "supersecret") == 0
    user = db_session.query(User).filter_by(username="kevin").one()
    assert _created(fired, "kevin") == [{"id": user.id, "username": "kevin", "is_admin": True}]
    rows = _audit(db_session, "kevin")
    assert [(r.action, r.actor_type, r.actor_label) for r in rows] == [
        ("user.created", "system", "cli")
    ]
    assert synced == [["kevin"]]


def test_env_admin_at_startup(db_session, monkeypatch, fired, synced):
    import app.main as m

    monkeypatch.setattr(m, "ADMIN_PASSWORD", "startpass1")
    try:
        m._ensure_admin(db_session)
    finally:
        BOOTSTRAP_SETUP_FILE.unlink(missing_ok=True)
        BOOTSTRAP_TOKEN_FILE.unlink(missing_ok=True)
    user = db_session.query(User).filter_by(username="admin").one()
    assert user.is_admin
    assert _created(fired, "admin") == [{"id": user.id, "username": "admin", "is_admin": True}]
    rows = _audit(db_session, "admin")
    assert [(r.action, r.actor_type, r.actor_label) for r in rows] == [
        ("user.created", "system", "startup")
    ]
    assert synced == [["admin"]]


def test_lost_race_raises_username_taken_without_event(db_session, fired, synced):
    # The service has no pre-check of its own, so a second insert of the name
    # reaches the unique constraint, as the loser of a real race does.
    actor = Actor("system", None, "cli", None)
    users_service.create_user(
        db_session, username="twin", password="twinpass1", is_admin=True, actor=actor
    )
    with pytest.raises(users_service.UsernameTaken):
        users_service.create_user(
            db_session, username="twin", password="otherpass1", is_admin=True, actor=actor
        )
    assert len(_created(fired, "twin")) == 1
    assert len(_audit(db_session, "twin")) == 1
    assert synced == [["twin"]]
    assert db_session.query(User).filter_by(username="twin").count() == 1
