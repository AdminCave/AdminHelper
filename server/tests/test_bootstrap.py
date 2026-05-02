"""Tests fuer den Bootstrap-Flow: Erst-Admin per Setup-Token statt Default 'admin/admin'.

Hintergrund: Pre-Release-Audit P0-6. Statt einem fixen 'admin/admin'-Default
generiert der Server beim ersten Start einen einmaligen Token in
DATA_DIR/.bootstrap_token. Der Endpoint POST /api/auth/bootstrap nimmt
diesen Token entgegen und legt damit den ersten Admin an.
"""

import secrets

import pytest

from app.core.auth import hash_api_key
from app.core.config import BOOTSTRAP_TOKEN_FILE
from app.modules.users.models import User


@pytest.fixture()
def fresh_token():
    """Schreibt einen frischen Bootstrap-Token, raeumt nach dem Test auf."""
    raw = secrets.token_urlsafe(32)
    BOOTSTRAP_TOKEN_FILE.write_text(hash_api_key(raw))
    yield raw
    if BOOTSTRAP_TOKEN_FILE.exists():
        BOOTSTRAP_TOKEN_FILE.unlink()


@pytest.fixture()
def no_token_file():
    """Stellt sicher, dass keine Bootstrap-Datei existiert (Cleanup vor + nach)."""
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

        # Token verbraucht
        assert not BOOTSTRAP_TOKEN_FILE.exists()

    def test_wrong_token_fails_and_does_not_consume_file(
        self, test_client, fresh_token
    ):
        res = test_client.post(
            "/api/auth/bootstrap",
            json={"token": "definitely-wrong", "username": "anyone", "password": "abcdefgh"},
        )
        assert res.status_code == 401
        # Token-Datei muss erhalten bleiben
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
        # Token-Datei bleibt — wird vom naechsten _ensure_admin aufgeraeumt

    def test_idempotency_after_successful_bootstrap(
        self, test_client, db_session, fresh_token
    ):
        # Erster Bootstrap: erfolgreich
        res1 = test_client.post(
            "/api/auth/bootstrap",
            json={"token": fresh_token, "username": "first", "password": "abcdefgh"},
        )
        assert res1.status_code == 201

        # Selbst wenn jemand die Token-Datei manipuliert und neu schreibt,
        # blockiert der "User-existiert"-Check.
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
        # Pydantic-Validation greift vor Endpoint-Logik
        assert res.status_code == 422
