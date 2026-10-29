# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Of a failure, the server log names only its type: no text, no traceback."""

import asyncio
import errno
import logging
import pathlib
import secrets

from app.core.auth import hash_api_key


def test_a_failed_sse_start_logs_only_the_error_type(monkeypatch, caplog):
    import app.core.events as events
    import app.main as m
    from app.modules.notifications import stream_hub

    monkeypatch.setattr(m, "_run_startup_tasks", lambda: None)
    monkeypatch.setattr(events, "fire_event", lambda *a, **k: None)

    async def boom(*_a, **_k):
        raise ConnectionError("redis://:s3cr3t-pw@redis.example:6379 unreachable")

    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(stream_hub, "start", boom)
    monkeypatch.setattr(stream_hub, "stop", noop)
    reached_yield = False

    async def scenario():
        nonlocal reached_yield
        async with m.lifespan(m.app):
            reached_yield = True

    with caplog.at_level(logging.WARNING):
        asyncio.run(scenario())
    assert reached_yield
    warnings = [r for r in caplog.records if r.name == "app.main" and r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "ConnectionError" in warnings[0].getMessage()
    assert "s3cr3t-pw" not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


def test_a_failed_bootstrap_file_removal_logs_only_the_error_type(
    test_client, tmp_path, monkeypatch, caplog
):
    import app.modules.users.auth_router as auth_router

    token_file = tmp_path / ".bootstrap_token"
    setup_file = tmp_path / ".bootstrap_setup"
    raw = secrets.token_urlsafe(32)
    token_file.write_text(hash_api_key(raw))
    setup_file.write_text(raw)
    monkeypatch.setattr(auth_router, "BOOTSTRAP_TOKEN_FILE", token_file)
    monkeypatch.setattr(auth_router, "BOOTSTRAP_SETUP_FILE", setup_file)

    real_unlink = pathlib.Path.unlink

    def unlink(self, *args, **kwargs):
        if self == setup_file:
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", unlink)
    with caplog.at_level(logging.WARNING):
        res = test_client.post(
            "/api/auth/bootstrap",
            json={"token": raw, "username": "first", "password": "abcdefgh"},
        )
    assert res.status_code == 201, res.text
    assert not token_file.exists()
    warnings = [
        r
        for r in caplog.records
        if r.name == "adminhelper.auth_router" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert ".bootstrap_setup" in warnings[0].getMessage()
    assert "PermissionError" in warnings[0].getMessage()
    assert "Permission denied" not in caplog.text
