# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A NUL byte in the path or the query string is refused before routing.

Path and query parameters are function arguments, not models, so no field type
guards them as a class. A `%00` in a string path parameter or a string query
value used to reach a comparison against a text column, psycopg raised DataError
while binding it, and the client got HTTP 500. Reproduced 2026-09-23 on every
route below; the path cases are the ones tests/schemathesis_exclude.toml names
for update_server, update_tunnel and update_playbook, the query cases the two
filters of list_tunnels."""

import pytest

NUL = chr(0)

# GET routes whose string path parameter goes straight into `Model.id == value`.
PATH_ROUTES = (
    "/api/servers/{}",
    "/api/ansible/playbooks/{}",
    "/api/frp/tunnels/{}",
    "/api/frp/server-config/{}",
    "/api/hooks/{}",
)


def _login(test_client) -> dict:
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.parametrize("route", PATH_ROUTES)
def test_a_nul_in_a_path_parameter_is_422(route, test_client, db_session, admin_user):
    headers = _login(test_client)

    # An id that does not exist answers 404 — the value reached the lookup.
    ok = test_client.get(route.format("ghost"), headers=headers)
    assert ok.status_code == 404, f"{route}: {ok.status_code} {ok.text}"

    nul = test_client.get(route.format("a%00b"), headers=headers)
    assert nul.status_code == 422, f"{route}: {nul.status_code} {nul.text}"
    assert nul.json()["detail"][0]["loc"] == ["path"]


@pytest.mark.parametrize("field", ("server_id", "frp_config_id"))
def test_a_nul_in_a_query_value_is_422(field, test_client, db_session, admin_user):
    headers = _login(test_client)

    ok = test_client.get("/api/frp/tunnels", params={field: "ghost"}, headers=headers)
    assert ok.status_code == 200, f"{field}: {ok.status_code} {ok.text}"

    nul = test_client.get("/api/frp/tunnels", params={field: "a" + NUL + "b"}, headers=headers)
    assert nul.status_code == 422, f"{field}: {nul.status_code} {nul.text}"
    assert nul.json()["detail"][0]["loc"] == ["query", field]


def test_a_nul_in_a_query_name_is_422(test_client, db_session, admin_user):
    headers = _login(test_client)
    r = test_client.get("/api/frp/tunnels", params={"a" + NUL: "1"}, headers=headers)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["query", "a" + NUL]


def test_the_guard_answers_before_routing(test_client):
    # No route matches, and no credentials are sent: a 404 or a 401 would mean
    # the request got past the guard into routing or into a dependency.
    assert test_client.get("/api/no-such-route/a%00b").status_code == 422
    assert test_client.get("/api/servers/a%00b").status_code == 422
    assert test_client.get("/api/frp/tunnels", params={"server_id": NUL}).status_code == 422


def test_an_encoded_percent_sign_is_not_a_nul(test_client, db_session, admin_user):
    # `%2500` decodes once, to the three characters "%00"; the guard must not
    # decode a second time. Query only: for the PATH, Starlette's TestClient
    # itself decodes twice (httpx's url.path is already decoded, and it unquotes
    # again), so `/a%2500b` arrives as a NUL here but not under uvicorn.
    headers = _login(test_client)
    r = test_client.get("/api/frp/tunnels?server_id=a%2500b", headers=headers)
    assert r.status_code == 200, r.text
