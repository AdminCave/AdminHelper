# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The actor headers the server's proxy sets (R-1636): decoded, cleaned of control
characters, the name capped at 64 characters, a header over 1024 characters refused, and
without them the actor stays empty."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.actor import ACTOR_HEADER_MAX, ACTOR_NAME_MAX, Actor, request_actor


def _request(**headers):
    raw = [(k.lower().encode(), v.encode("latin-1")) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


def _actor(actor_id=None, name=None):
    headers = {}
    if actor_id is not None:
        headers["X-AH-Actor-Id"] = actor_id
    if name is not None:
        headers["X-AH-Actor-Name"] = name
    return request_actor(_request(**headers))


def test_without_headers_the_actor_is_empty():
    assert _actor() == Actor(None, None)


def test_the_name_is_decoded():
    assert _actor("user:7", "j%C3%BCrgen%20m%C3%BCller") == Actor("user:7", "jürgen müller")


def test_control_characters_are_removed():
    assert _actor("user:7%0A", "ad%0D%0Amin%00%1B[31m") == Actor("user:7", "admin[31m")


def test_an_invalid_encoding_becomes_the_replacement_character():
    assert _actor(name="a%FFb") == Actor(None, "a�b")


def test_the_name_is_capped():
    assert _actor(name="x" * 200).name == "x" * ACTOR_NAME_MAX
    # Capped after decoding: 64 characters, not 64 bytes of the encoding.
    assert _actor(name="%C3%BC" * 100).name == "ü" * ACTOR_NAME_MAX


def test_an_empty_or_control_only_value_is_none():
    assert _actor("", "%00%0A") == Actor(None, None)


@pytest.mark.parametrize("header", ["X-AH-Actor-Id", "X-AH-Actor-Name"])
def test_a_header_over_the_limit_is_refused(header):
    assert request_actor(_request(**{header: "x" * ACTOR_HEADER_MAX})) is not None
    with pytest.raises(HTTPException) as exc:
        request_actor(_request(**{header: "x" * (ACTOR_HEADER_MAX + 1)}))
    assert exc.value.status_code == 400


def test_an_oversized_header_is_a_400_at_the_route(client_db):
    client, _ = client_db
    payload = {"scope_kind": "all", "effect": "no_notify", "duration_kind": "permanent"}
    long_name = {"X-AH-Actor-Name": "x" * (ACTOR_HEADER_MAX + 1)}
    assert client.post("/exceptions", json=payload, headers=long_name).status_code == 400
    assert client.get("/exceptions").json() == []
