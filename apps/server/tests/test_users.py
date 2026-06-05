# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Input validation on the users endpoints (GHSA-g95r): password min-length
and username charset (the username is interpolated into FRP TOML / PKI file
names, so it must be restricted)."""


def _admin_headers(test_client) -> dict:
    login = test_client.post(
        "/api/auth/login", json={"username": "admin", "password": "adminpass"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


class TestUserCreateValidation:
    def test_short_password_rejected(self, test_client, admin_user):
        res = test_client.post(
            "/api/users",
            headers=_admin_headers(test_client),
            json={"username": "alice", "password": "short"},
        )
        assert res.status_code == 422

    def test_bad_username_charset_rejected(self, test_client, admin_user):
        for bad in ["bad name", "evil;rm", 'a"b', "a\nb", "tab\tname"]:
            res = test_client.post(
                "/api/users",
                headers=_admin_headers(test_client),
                json={"username": bad, "password": "validpass123"},
            )
            assert res.status_code == 422, f"{bad!r} must be rejected"

    def test_valid_user_accepted(self, test_client, admin_user):
        res = test_client.post(
            "/api/users",
            headers=_admin_headers(test_client),
            json={"username": "bob.k-1", "password": "validpass123"},
        )
        assert res.status_code == 201, res.text


class TestUserUpdateValidation:
    def test_short_password_on_update_rejected(self, test_client, admin_user):
        res = test_client.put(
            f"/api/users/{admin_user.id}",
            headers=_admin_headers(test_client),
            json={"password": "short"},
        )
        assert res.status_code == 422
