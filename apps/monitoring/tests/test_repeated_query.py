# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A query parameter the schema declares as one value, sent twice, is a 422 (R-1131).

FastAPI read the last of them and answered 200; schemathesis (ST201, weekly run
2026-11-04) sent `offset=…&offset=…` to GET /checks and saw the request it had
built against the schema as invalid pass."""

import pytest


@pytest.mark.parametrize(
    "path, name",
    [("/checks", "offset"), ("/checks", "limit"), ("/status", "offset"), ("/alerts", "limit")],
)
def test_repeated_scalar_query_parameter_is_422(client_db, path, name):
    client, _ = client_db
    r = client.get(f"{path}?{name}=1&{name}=2")
    assert r.status_code == 422, f"{path} with {name} twice: {r.status_code} {r.text}"
    detail = r.json()["detail"]
    assert [d["loc"] for d in detail] == [["query", name]], detail
    assert detail[0]["input"] == ["1", "2"], detail


def test_single_value_and_undeclared_repeat_pass(client_db):
    client, _ = client_db
    assert client.get("/checks?offset=1").status_code == 200
    # Only declared parameters are checked: an unknown one stays ignored, as before.
    assert client.get("/checks?unknown=1&unknown=2").status_code == 200
