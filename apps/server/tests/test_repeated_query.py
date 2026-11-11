# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A query parameter the schema declares as one value, sent twice, is a 422 (R-1132).

FastAPI read the last of them and answered 200, as in the monitoring service before
R-1131: `offset=1&offset=2` passed a request the published schema calls invalid."""

import pytest


def _login(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.parametrize(
    "path, name",
    [
        ("/api/connections", "offset"),
        ("/api/connections", "limit"),
        ("/api/servers", "offset"),
        ("/api/audit", "action"),
    ],
)
def test_repeated_scalar_query_parameter_is_422(test_client, db_session, admin_user, path, name):
    r = test_client.get(f"{path}?{name}=1&{name}=2", headers=_login(test_client))
    assert r.status_code == 422, f"{path} with {name} twice: {r.status_code} {r.text}"
    detail = r.json()["detail"]
    assert [d["loc"] for d in detail] == [["query", name]], detail
    assert detail[0]["input"] == ["1", "2"], detail


def test_single_value_and_undeclared_repeat_pass(test_client, db_session, admin_user):
    headers = _login(test_client)
    assert test_client.get("/api/connections?offset=1", headers=headers).status_code == 200
    # Only declared parameters are checked: an unknown one stays ignored, as before.
    r = test_client.get("/api/connections?unknown=1&unknown=2", headers=headers)
    assert r.status_code == 200, r.text
