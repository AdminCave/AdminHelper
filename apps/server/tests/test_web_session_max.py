# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-0887: a browser session ends on the server WEB_SESSION_MAX_HOURS after its sign-in,
however often the refresh cookie rotates. Desktop, CLI and scripts are not limited."""

import time

import jwt
import pytest

from app.core import config
from app.core.auth import create_refresh_token
from app.core.config import ALGORITHM, SECRET_KEY, parse_web_session_max_hours
from tests.token_claims import claims_for

BROWSER = {"Sec-Fetch-Site": "same-origin"}
CREDS = {"username": "admin", "password": "adminpass"}
HOUR = 3600


def _claims(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})


@pytest.fixture(autouse=True)
def _max_24h(monkeypatch):
    monkeypatch.setattr(config, "WEB_SESSION_MAX_HOURS", 24)


def _browser_login(client) -> str:
    login = client.post("/api/auth/login", json=CREDS, headers=BROWSER)
    assert login.status_code == 200
    return client.cookies.get("refresh_token")


def _set_cookie(client, token: str) -> None:
    client.cookies.clear()
    client.cookies.set("refresh_token", token, path="/api/auth")


class TestBrowserSession:
    def test_login_marks_the_refresh_token_as_web(self, test_client, admin_user):
        before = int(time.time())
        claims = _claims(_browser_login(test_client))
        assert claims["web"] is True
        assert before <= claims["auth_time"] <= int(time.time())

    def test_rotation_keeps_the_sign_in_time(self, test_client, admin_user):
        first = _claims(_browser_login(test_client))
        rot = test_client.post("/api/auth/refresh", headers=BROWSER)
        assert rot.status_code == 200
        rotated = _claims(test_client.cookies.get("refresh_token"))
        assert rotated["web"] is True
        assert rotated["auth_time"] == first["auth_time"]

    def test_refresh_after_the_limit_is_refused_and_clears_the_cookie(
        self, test_client, admin_user
    ):
        old = create_refresh_token(
            {**claims_for("admin"), "web": True, "auth_time": int(time.time()) - 24 * HOUR - 5}
        )
        _set_cookie(test_client, old)

        denied = test_client.post("/api/auth/refresh", headers=BROWSER)

        assert denied.status_code == 401
        set_cookie = denied.headers.get("set-cookie", "").lower()
        assert "refresh_token=" in set_cookie
        assert "max-age=0" in set_cookie

    def test_a_refused_refresh_is_no_reuse(self, test_client, admin_user):
        # The session ran out; a fresh sign-in must still work, and so must the token of
        # another session that was issued before (no watermark from a reuse alarm).
        other = test_client.post("/api/auth/login", json=CREDS).json()["refresh_token"]
        old = create_refresh_token(
            {**claims_for("admin"), "web": True, "auth_time": int(time.time()) - 25 * HOUR}
        )
        _set_cookie(test_client, old)
        assert test_client.post("/api/auth/refresh", headers=BROWSER).status_code == 401

        test_client.cookies.clear()
        assert (
            test_client.post("/api/auth/refresh", json={"refresh_token": other}).status_code == 200
        )

    def test_web_claim_counts_in_the_body_too(self, test_client, admin_user):
        # Moving the cookie value into the body does not get around the limit.
        old = create_refresh_token(
            {**claims_for("admin"), "web": True, "auth_time": int(time.time()) - 25 * HOUR}
        )
        test_client.cookies.clear()
        denied = test_client.post("/api/auth/refresh", json={"refresh_token": old})
        assert denied.status_code == 401

    def test_access_token_ends_with_the_session(self, test_client, admin_user):
        auth_time = int(time.time()) - 23 * HOUR
        _set_cookie(
            test_client,
            create_refresh_token({**claims_for("admin"), "web": True, "auth_time": auth_time}),
        )

        rot = test_client.post("/api/auth/refresh", headers=BROWSER)

        assert rot.status_code == 200
        assert _claims(rot.json()["access_token"])["exp"] <= auth_time + 24 * HOUR

    def test_cookie_token_from_before_the_update_counts_from_its_iat(
        self, test_client, admin_user, monkeypatch
    ):
        legacy = create_refresh_token(claims_for("admin"))  # no web, no auth_time
        iat = _claims(legacy)["iat"]
        monkeypatch.setattr(time, "time", lambda: iat + 24 * HOUR + 5)
        _set_cookie(test_client, legacy)

        denied = test_client.post("/api/auth/refresh", headers=BROWSER)

        assert denied.status_code == 401

    def test_cookie_token_from_before_the_update_rotates_into_a_web_token(
        self, test_client, admin_user
    ):
        legacy = create_refresh_token(claims_for("admin"))
        _set_cookie(test_client, legacy)

        rot = test_client.post("/api/auth/refresh", headers=BROWSER)

        assert rot.status_code == 200
        rotated = _claims(rot.cookies["refresh_token"])
        assert rotated["web"] is True
        assert rotated["auth_time"] == _claims(legacy)["iat"]

    def test_zero_turns_the_limit_off(self, test_client, admin_user, monkeypatch):
        monkeypatch.setattr(config, "WEB_SESSION_MAX_HOURS", 0)
        old = create_refresh_token(
            {**claims_for("admin"), "web": True, "auth_time": int(time.time()) - 100 * HOUR}
        )
        _set_cookie(test_client, old)
        assert test_client.post("/api/auth/refresh", headers=BROWSER).status_code == 200


class TestOtherClients:
    def test_desktop_login_is_not_marked_web(self, test_client, admin_user):
        login = test_client.post("/api/auth/login", json=CREDS)
        claims = _claims(login.json()["refresh_token"])
        assert "web" not in claims
        assert "auth_time" not in claims

    def test_desktop_token_in_the_body_outlives_the_limit(
        self, test_client, admin_user, monkeypatch
    ):
        token = test_client.post("/api/auth/login", json=CREDS).json()["refresh_token"]
        iat = _claims(token)["iat"]
        test_client.cookies.clear()
        monkeypatch.setattr(time, "time", lambda: iat + 48 * HOUR)

        rot = test_client.post("/api/auth/refresh", json={"refresh_token": token})

        assert rot.status_code == 200
        assert "web" not in _claims(rot.json()["refresh_token"])


class TestParse:
    @pytest.mark.parametrize(
        ("raw", "hours"),
        [(None, 24), ("", 24), ("  ", 24), ("0", 0), ("12", 12), (" 48 ", 48)],
    )
    def test_valid(self, raw, hours):
        assert parse_web_session_max_hours(raw) == hours

    @pytest.mark.parametrize("raw", ["-1", "abc", "1.5", "24h"])
    def test_invalid_falls_back_with_a_warning(self, raw, caplog):
        with caplog.at_level("WARNING"):
            assert parse_web_session_max_hours(raw) == 24
        assert "WEB_SESSION_MAX_HOURS" in caplog.text
