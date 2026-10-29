# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the bootstrap flow: first admin via setup token instead of the default 'admin/admin'.

Background: pre-release audit P0-6. Instead of a fixed 'admin/admin' default,
the server generates a one-time token in DATA_DIR/.bootstrap_token on first
start. The endpoint POST /api/auth/bootstrap accepts this token and uses it to
create the first admin.
"""

import errno
import logging
import os
import pathlib
import secrets
import stat

import pytest

from app.core.auth import hash_api_key
from app.core.config import BOOTSTRAP_TOKEN_FILE
from app.modules.users.models import User


@pytest.fixture()
def fresh_token():
    """Writes a fresh bootstrap token and cleans up after the test."""
    raw = secrets.token_urlsafe(32)
    BOOTSTRAP_TOKEN_FILE.write_text(hash_api_key(raw))
    yield raw
    if BOOTSTRAP_TOKEN_FILE.exists():
        BOOTSTRAP_TOKEN_FILE.unlink()


@pytest.fixture()
def no_token_file():
    """Ensures no bootstrap file exists (cleanup before + after)."""
    if BOOTSTRAP_TOKEN_FILE.exists():
        BOOTSTRAP_TOKEN_FILE.unlink()
    yield
    if BOOTSTRAP_TOKEN_FILE.exists():
        BOOTSTRAP_TOKEN_FILE.unlink()


class TestBootstrapEndpoint:
    def test_valid_token_creates_admin_and_returns_tokens(
        self, test_client, db_session, fresh_token
    ):
        res = test_client.post(
            "/api/auth/bootstrap",
            json={"token": fresh_token, "username": "first", "password": "abcdefgh"},
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert "access_token" in body
        assert "refresh_token" in body

        user = db_session.query(User).filter(User.username == "first").first()
        assert user is not None
        assert user.is_admin

        # Token consumed
        assert not BOOTSTRAP_TOKEN_FILE.exists()

    def test_browser_bootstrap_gets_the_refresh_token_only_as_cookie(
        self, test_client, fresh_token
    ):
        res = test_client.post(
            "/api/auth/bootstrap",
            json={"token": fresh_token, "username": "first", "password": "abcdefgh"},
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        assert res.status_code == 201, res.text
        assert res.json()["refresh_token"] == ""
        assert res.json()["access_token"]
        assert test_client.cookies.get("refresh_token")
        assert "httponly" in res.headers.get("set-cookie", "").lower()

    def test_wrong_token_fails_and_does_not_consume_file(self, test_client, fresh_token):
        res = test_client.post(
            "/api/auth/bootstrap",
            json={"token": "definitely-wrong", "username": "anyone", "password": "abcdefgh"},
        )
        assert res.status_code == 401
        # The token file must be preserved
        assert BOOTSTRAP_TOKEN_FILE.exists()

    def test_no_token_file_fails(self, test_client, no_token_file):
        res = test_client.post(
            "/api/auth/bootstrap",
            json={"token": "any", "username": "anyone", "password": "abcdefgh"},
        )
        assert res.status_code == 401

    def test_existing_admin_blocks_bootstrap(self, test_client, admin_user, fresh_token):
        res = test_client.post(
            "/api/auth/bootstrap",
            json={"token": fresh_token, "username": "second", "password": "abcdefgh"},
        )
        assert res.status_code == 409
        # Token file remains — cleaned up by the next _ensure_admin

    def test_idempotency_after_successful_bootstrap(self, test_client, db_session, fresh_token):
        # First bootstrap: successful
        res1 = test_client.post(
            "/api/auth/bootstrap",
            json={"token": fresh_token, "username": "first", "password": "abcdefgh"},
        )
        assert res1.status_code == 201

        # Even if someone tampers with and rewrites the token file,
        # the "user exists" check blocks it.
        BOOTSTRAP_TOKEN_FILE.write_text(hash_api_key("recreated"))
        try:
            res2 = test_client.post(
                "/api/auth/bootstrap",
                json={"token": "recreated", "username": "second", "password": "abcdefgh"},
            )
            assert res2.status_code == 409
        finally:
            if BOOTSTRAP_TOKEN_FILE.exists():
                BOOTSTRAP_TOKEN_FILE.unlink()

    def test_short_password_rejected_by_pydantic(self, test_client, fresh_token):
        res = test_client.post(
            "/api/auth/bootstrap",
            json={"token": fresh_token, "username": "anyone", "password": "short"},
        )
        # Pydantic validation takes effect before the endpoint logic
        assert res.status_code == 422


def test_bootstrap_token_written_to_file_not_log(caplog):
    """3.91: the raw setup token lands in a 0600 file, never in the log."""
    import logging

    from app.core.config import BOOTSTRAP_SETUP_FILE, BOOTSTRAP_TOKEN_FILE
    from app.main import _emit_bootstrap_token

    try:
        with caplog.at_level(logging.WARNING):
            _emit_bootstrap_token()
        assert BOOTSTRAP_SETUP_FILE.exists()
        raw = BOOTSTRAP_SETUP_FILE.read_text().strip()
        assert raw
        assert raw not in caplog.text  # the raw token is never logged (3.91)
        assert BOOTSTRAP_TOKEN_FILE.read_text().strip() != raw  # hash file holds the hash
    finally:
        BOOTSTRAP_SETUP_FILE.unlink(missing_ok=True)
        BOOTSTRAP_TOKEN_FILE.unlink(missing_ok=True)


@pytest.fixture()
def bootstrap_files(tmp_path, monkeypatch):
    """The bootstrap files of app.main in tmp_path instead of the shared test DATA_DIR."""
    import app.main as m

    token_file = tmp_path / ".bootstrap_token"
    setup_file = tmp_path / ".bootstrap_setup"
    monkeypatch.setattr(m, "BOOTSTRAP_TOKEN_FILE", token_file)
    monkeypatch.setattr(m, "BOOTSTRAP_SETUP_FILE", setup_file)
    return token_file, setup_file


@pytest.fixture()
def umask_zero():
    # Under umask 0 a file created with the default mode is 0666: only a mode set at creation
    # keeps it private.
    previous = os.umask(0)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture()
def no_chmod(monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(pathlib.Path, "chmod", refuse)
    monkeypatch.setattr(os, "chmod", refuse)


def test_bootstrap_files_are_0600_from_the_start(bootstrap_files, umask_zero, no_chmod, caplog):
    """Both bootstrap files are private from their creation on, whatever the umask, with no
    chmod afterwards whose error could get lost: here every chmod fails."""
    from app.main import _emit_bootstrap_token

    token_file, setup_file = bootstrap_files
    with caplog.at_level(logging.WARNING):
        _emit_bootstrap_token()

    raw = setup_file.read_text(encoding="utf-8")
    assert raw
    assert stat.S_IMODE(setup_file.lstat().st_mode) == 0o600
    assert stat.S_IMODE(token_file.lstat().st_mode) == 0o600
    assert token_file.read_text(encoding="utf-8") == hash_api_key(raw)
    assert raw not in token_file.read_text(encoding="utf-8")
    assert raw not in caplog.text  # the raw token is never logged (3.91)
    assert sorted(p.name for p in token_file.parent.iterdir()) == [
        ".bootstrap_setup",
        ".bootstrap_token",
    ], "no temp file may stay behind"


@pytest.mark.parametrize("failing", [".bootstrap_setup", ".bootstrap_token"])
def test_a_failed_bootstrap_file_removal_is_logged(bootstrap_files, monkeypatch, caplog, failing):
    """A bootstrap file that cannot be removed is named in the log with the type of the error,
    and the other one is removed all the same."""
    import app.main as m

    token_file, setup_file = bootstrap_files
    token_file.write_text("hash")
    setup_file.write_text("raw")
    stuck = token_file.parent / failing
    other = setup_file if stuck == token_file else token_file
    real_unlink = pathlib.Path.unlink

    def unlink(self, missing_ok=False):
        if self == stuck:
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(pathlib.Path, "unlink", unlink)
    with caplog.at_level(logging.INFO, logger=m.logger.name):
        m._purge_bootstrap_files()

    assert not other.exists()
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.name == m.logger.name and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert failing in warnings[0] and "PermissionError" in warnings[0]
    assert "Permission denied" not in caplog.text
    assert not [r for r in caplog.records if r.exc_info]


def test_short_env_admin_password_falls_back_to_bootstrap(db_session, monkeypatch):
    """3.90: an ADMIN_PASSWORD < 8 chars must not create an admin — fall back to the
    bootstrap-token path instead of silently making a weak-password prod admin."""
    import app.main as m
    from app.core.config import BOOTSTRAP_SETUP_FILE, BOOTSTRAP_TOKEN_FILE
    from app.modules.users.models import User

    monkeypatch.setattr(m, "ADMIN_PASSWORD", "abc")  # < 8 chars
    try:
        m._ensure_admin(db_session)
        assert db_session.query(User).filter(User.username == "admin").count() == 0
        assert BOOTSTRAP_TOKEN_FILE.exists()  # bootstrap emitted instead
    finally:
        BOOTSTRAP_SETUP_FILE.unlink(missing_ok=True)
        BOOTSTRAP_TOKEN_FILE.unlink(missing_ok=True)


def test_lifespan_survives_redis_outage_at_boot(monkeypatch):
    """4.68: Redis carries only the optional SSE push fan-out (rate-limit degrades to in-memory,
    SSE has a polling fallback). If stream_hub.start raises at boot (compose race, a Redis
    restart during a redeploy), the lifespan must still reach yield — the server must start, not
    crash-loop, on an optional channel being briefly unavailable."""
    import asyncio

    import app.core.events as events
    import app.main as m
    from app.modules.notifications import stream_hub

    monkeypatch.setattr(m, "_run_startup_tasks", lambda: None)
    monkeypatch.setattr(events, "fire_event", lambda *a, **k: None)

    async def _boom(*_a, **_k):
        raise ConnectionError("redis down at boot")

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(stream_hub, "start", _boom)
    monkeypatch.setattr(stream_hub, "stop", _noop)

    reached_yield = False

    async def scenario():
        nonlocal reached_yield
        async with m.lifespan(m.app):
            reached_yield = True

    asyncio.run(scenario())
    assert reached_yield  # the server started despite the Redis outage


def test_bootstrap_admin_gets_default_subscription(test_client, db_session, fresh_token):
    """T30: the bootstrap-token admin is the only user a fresh install has —
    it must start with the bell-only baseline subscription."""
    from app.modules.notifications.models import NotificationSubscription

    res = test_client.post(
        "/api/auth/bootstrap",
        json={"token": fresh_token, "username": "first", "password": "abcdefgh"},
    )
    assert res.status_code == 201, res.text
    user = db_session.query(User).filter(User.username == "first").one()
    sub = (
        db_session.query(NotificationSubscription)
        .filter(NotificationSubscription.user_id == user.id)
        .one()
    )
    assert (sub.scope_type, sub.min_severity) == ("all", "warning")
    assert sub.enabled is True
    assert sub.channel_email is False
    assert sub.channel_telegram is False


def test_env_admin_gets_default_subscription(db_session, monkeypatch):
    """T30: same baseline for the ADMIN_PASSWORD env path of _ensure_admin."""
    import app.main as m
    from app.modules.notifications.models import NotificationSubscription

    monkeypatch.setattr(m, "ADMIN_PASSWORD", "supersecret")
    m._ensure_admin(db_session)
    user = db_session.query(User).filter(User.username == "admin").one()
    sub = (
        db_session.query(NotificationSubscription)
        .filter(NotificationSubscription.user_id == user.id)
        .one()
    )
    assert (sub.scope_type, sub.min_severity) == ("all", "warning")


def test_two_concurrent_bootstraps_with_the_token_create_one_admin(pg_engine, monkeypatch):
    # Two workers, each with its own session that really commits. The barrier inside
    # hash_password holds the first call until the second has checked "no user" too, so
    # without a lock both create an admin; with it the second waits before its check,
    # the barrier times out and the first goes on alone.
    import threading

    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    import app.modules.users.auth_router as auth_router
    from app.core.database import get_db
    from app.main import app

    raw = secrets.token_urlsafe(32)
    BOOTSTRAP_TOKEN_FILE.write_text(hash_api_key(raw))
    new_session = sessionmaker(bind=pg_engine)

    def _own_session():
        session = new_session()
        try:
            yield session
        finally:
            session.close()

    barrier = threading.Barrier(2)
    real_hash = auth_router.hash_password

    def _hash_after_both_checked(password):
        try:
            barrier.wait(timeout=3)
        except threading.BrokenBarrierError:
            pass
        return real_hash(password)

    monkeypatch.setattr(auth_router, "hash_password", _hash_after_both_checked)
    app.dependency_overrides[get_db] = _own_session
    names = ("first-a", "first-b")
    statuses: dict[str, int] = {}

    def _bootstrap(name):
        res = TestClient(app).post(
            "/api/auth/bootstrap",
            json={"token": raw, "username": name, "password": "abcdefgh"},
        )
        statuses[name] = res.status_code

    try:
        threads = [threading.Thread(target=_bootstrap, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        with pg_engine.connect() as conn:
            admins = (
                conn.execute(
                    text("SELECT username FROM users WHERE username = ANY(:names)").bindparams(
                        names=list(names)
                    ),
                )
                .scalars()
                .all()
            )
    finally:
        app.dependency_overrides.clear()
        with pg_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM audit_log WHERE object_label = ANY(:names)").bindparams(
                    names=list(names)
                )
            )
            conn.execute(
                text("DELETE FROM users WHERE username = ANY(:names)").bindparams(names=list(names))
            )
        BOOTSTRAP_TOKEN_FILE.unlink(missing_ok=True)
    assert len(admins) == 1, (admins, statuses)
    assert sorted(statuses.values()) == [201, 409], statuses
