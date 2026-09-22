# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Both edges of the int-id bound on the routes that take one
(input-boundary-validation, T4).

Unlike the pagination offsets, this is where the class was first measured: an
id past the INTEGER width of the column reached the comparison and Postgres
answered NumericValueOutOfRange, uncaught, so HTTP 500 instead of 422
(tests/schemathesis_exclude.toml, reproduced 2026-09-21: 2147483647 -> 404,
2147483648 -> 500). The highest id the column can hold must still resolve
normally — a bound that rejects it would make valid ids unreachable."""

import pytest

from app.modules.frp.models import FrpServerConfig

INT_PK_MAX = 2147483647  # app.core.bounds.IntPk — users.id and api_keys.id are Column(Integer)


def _login(test_client) -> dict:
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def _frp_config(db_session):
    """The visitor-toml route resolves an FRP config before it ever looks at
    user_id — without one it 404s for that reason instead, and the probe would
    prove nothing."""
    db_session.add(
        FrpServerConfig(id="cfg-1", name="c", server_addr="frps.example", auth_token="t" * 16)
    )
    db_session.commit()


@pytest.mark.parametrize("method,body", [("put", {}), ("delete", None)])
def test_user_path_id_holds_at_both_edges(method, body, test_client, db_session, admin_user):
    headers = _login(test_client)
    call = getattr(test_client, method)
    kwargs = {} if body is None else {"json": body}

    highest = call(f"/api/users/{INT_PK_MAX}", headers=headers, **kwargs)
    assert highest.status_code == 404, f"{method}: {highest.status_code} {highest.text}"
    assert highest.json()["detail"] == "Benutzer nicht gefunden"

    past = call(f"/api/users/{INT_PK_MAX + 1}", headers=headers, **kwargs)
    assert past.status_code == 422, f"{method}: {past.status_code} {past.text}"


def test_api_key_path_id_holds_at_both_edges(test_client, db_session, admin_user):
    headers = _login(test_client)
    highest = test_client.delete(f"/api/api-keys/{INT_PK_MAX}", headers=headers)
    assert highest.status_code == 404, highest.text
    assert highest.json()["detail"] == "API-Key nicht gefunden"

    past = test_client.delete(f"/api/api-keys/{INT_PK_MAX + 1}", headers=headers)
    assert past.status_code == 422, past.text


def test_visitor_toml_user_id_holds_at_both_edges(test_client, db_session, admin_user, _frp_config):
    headers = _login(test_client)
    highest = test_client.get(
        f"/api/frp/generate/visitor-toml?user_id={INT_PK_MAX}", headers=headers
    )
    assert highest.status_code == 404, highest.text
    assert highest.json()["detail"] == "Benutzer nicht gefunden"

    past = test_client.get(
        f"/api/frp/generate/visitor-toml?user_id={INT_PK_MAX + 1}", headers=headers
    )
    assert past.status_code == 422, past.text


def test_zero_and_negative_ids_are_rejected(test_client, db_session, admin_user):
    """ge=1 is part of the bound: a table's id sequence starts at 1, so 0 and -1
    were never valid — they used to reach the query and answer 404."""
    headers = _login(test_client)
    for path in ("/api/users/0", "/api/users/-1", "/api/api-keys/0", "/api/api-keys/-1"):
        r = test_client.delete(path, headers=headers)
        assert r.status_code == 422, f"{path}: {r.status_code} {r.text}"
