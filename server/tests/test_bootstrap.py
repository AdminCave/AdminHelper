# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the bootstrap flow: first admin via setup token instead of the default 'admin/admin'.

Background: pre-release audit P0-6. Instead of a fixed 'admin/admin' default,
the server generates a one-time token in DATA_DIR/.bootstrap_token on first
start. The endpoint POST /api/auth/bootstrap accepts this token and uses it to
create the first admin.
"""

import secrets

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

    def test_wrong_token_fails_and_does_not_consume_file(
        self, test_client, fresh_token
    ):
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

    def test_existing_admin_blocks_bootstrap(
        self, test_client, admin_user, fresh_token
    ):
        res = test_client.post(
            "/api/auth/bootstrap",
            json={"token": fresh_token, "username": "second", "password": "abcdefgh"},
        )
        assert res.status_code == 409
        # Token file remains — cleaned up by the next _ensure_admin

    def test_idempotency_after_successful_bootstrap(
        self, test_client, db_session, fresh_token
    ):
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
