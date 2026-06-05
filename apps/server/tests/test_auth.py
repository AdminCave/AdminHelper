# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for auth functions: password hashing, token creation, token validation."""

from datetime import timedelta

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    hash_api_key,
    generate_api_key,
    _get_user_from_token,
    get_user_from_refresh_token,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("geheim123")
        assert verify_password("geheim123", hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("geheim123")
        assert not verify_password("falsch", hashed)

    def test_long_password_over_72_bytes(self):
        """bcrypt has a 72-byte limit; the prehash must absorb that."""
        long_pw = "A" * 200
        hashed = hash_password(long_pw)
        assert verify_password(long_pw, hashed)
        assert not verify_password("A" * 199, hashed)

    def test_unicode_password(self):
        pw = "Passwört-mit-Ümläuten-🔑"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed)


class TestApiKeyUtils:
    def test_generate_api_key_is_unique(self):
        keys = {generate_api_key() for _ in range(50)}
        assert len(keys) == 50

    def test_hash_api_key_deterministic(self):
        key = "test-key-123"
        assert hash_api_key(key) == hash_api_key(key)

    def test_hash_api_key_different_for_different_keys(self):
        assert hash_api_key("key-a") != hash_api_key("key-b")


class TestTokenCreation:
    def test_access_token_decodes(self):
        import jwt
        from app.core.config import SECRET_KEY, ALGORITHM

        token = create_access_token({"sub": "admin"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "admin"
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_refresh_token_type(self):
        import jwt
        from app.core.config import SECRET_KEY, ALGORITHM

        token = create_refresh_token({"sub": "admin"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["type"] == "refresh"

    def test_custom_expiration(self):
        import jwt
        from app.core.config import SECRET_KEY, ALGORITHM

        token = create_access_token({"sub": "user1"}, expires_delta=timedelta(minutes=1))
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "user1"


class TestTokenValidation:
    def test_valid_access_token(self, db_session, admin_user):
        token = create_access_token({"sub": admin_user.username})
        user = _get_user_from_token(token, db_session)
        assert user is not None
        assert user.username == "admin"

    def test_refresh_token_rejected_as_access(self, db_session, admin_user):
        token = create_refresh_token({"sub": admin_user.username})
        user = _get_user_from_token(token, db_session)
        assert user is None

    def test_refresh_token_accepted_with_correct_type(self, db_session, admin_user):
        token = create_refresh_token({"sub": admin_user.username})
        user = get_user_from_refresh_token(token, db_session)
        assert user is not None
        assert user.username == "admin"

    def test_expired_token_returns_none(self, db_session, admin_user):
        token = create_access_token(
            {"sub": admin_user.username},
            expires_delta=timedelta(seconds=-10),
        )
        user = _get_user_from_token(token, db_session)
        assert user is None

    def test_invalid_token_returns_none(self, db_session):
        user = _get_user_from_token("not-a-real-jwt", db_session)
        assert user is None

    def test_nonexistent_user_returns_none(self, db_session):
        token = create_access_token({"sub": "ghost"})
        user = _get_user_from_token(token, db_session)
        assert user is None

    def test_missing_sub_returns_none(self, db_session):
        token = create_access_token({})
        user = _get_user_from_token(token, db_session)
        assert user is None


class TestRefreshRotation:
    """H-2: refresh-token rotation + reuse detection."""

    def test_refresh_rotates_and_blacklists_old(self, test_client, admin_user):
        login = test_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "adminpass"},
        )
        assert login.status_code == 200
        old_refresh = login.json()["refresh_token"]

        rot = test_client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert rot.status_code == 200
        new_refresh = rot.json()["refresh_token"]
        assert new_refresh != old_refresh

        # Reuse of the old refresh token must fail (reuse detection)
        reuse = test_client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert reuse.status_code == 401

    def test_logout_blacklists_refresh(self, test_client, admin_user):
        login = test_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "adminpass"},
        )
        access = login.json()["access_token"]
        refresh = login.json()["refresh_token"]

        out = test_client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {access}"},
            json={"refresh_token": refresh},
        )
        assert out.status_code == 200

        # Refresh after logout must fail
        denied = test_client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert denied.status_code == 401

    def test_logout_without_refresh_still_blacklists_access(self, test_client, admin_user):
        login = test_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "adminpass"},
        )
        access = login.json()["access_token"]

        out = test_client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert out.status_code == 200

        # /me with the blacklisted access token must fail
        me = test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 401
