# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The server's 422 is FastAPI's own, except that a non-finite number in the input it echoes
is null and a lone surrogate there is escaped.

Starlette reads a request body with json.loads, which takes the tokens Infinity, -Infinity and
NaN (RFC 8259, section 6, does not allow them). FastAPI's 422 echoes the body as input, and
JSONResponse refused to write such a number back, so the client got a 500 instead. The lone
surrogate on its own is pinned in test_frp_extra_config.py."""

import asyncio
import json

import pytest
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError

from app.main import _validation_error

_JSON = {"Content-Type": "application/json"}


def _strict_loads(content: bytes):
    """The answer as any client reads it: strict UTF-8, and no NaN or Infinity token."""

    def refuse(token):
        raise ValueError(f"not a JSON number: {token}")

    return json.loads(content.decode("utf-8"), parse_constant=refuse)


def _login(client, body: str):
    return client.post("/api/auth/login", content=body, headers=_JSON)


def _answer(handler, errors):
    response = asyncio.run(handler(None, RequestValidationError(errors)))
    return response.status_code, bytes(response.body)


@pytest.mark.parametrize("token", ["Infinity", "NaN", "-Infinity"])
def test_a_non_finite_number_in_the_input_is_null(test_client, token):
    r = _login(test_client, f'{{"username": {token}}}')
    assert (r.status_code, r.headers["content-type"]) == (422, "application/json")
    assert _strict_loads(r.content) == {
        "detail": [
            {
                "type": "string_type",
                "loc": ["body", "username"],
                "msg": "Input should be a valid string",
                "input": None,
            },
            {
                "type": "missing",
                "loc": ["body", "password"],
                "msg": "Field required",
                "input": {"username": None},
            },
        ]
    }


def test_a_nested_non_finite_number_is_null_beside_a_lone_surrogate(test_client):
    r = _login(test_client, '{"username": ["\\ud800", NaN, {"a": [Infinity, -Infinity, 1.5]}]}')
    assert (r.status_code, r.headers["content-type"]) == (422, "application/json")
    echoed = ["\ud800", None, {"a": [None, None, 1.5]}]
    assert _strict_loads(r.content) == {
        "detail": [
            {
                "type": "string_type",
                "loc": ["body", "username"],
                "msg": "Input should be a valid string",
                "input": echoed,
            },
            {
                "type": "missing",
                "loc": ["body", "password"],
                "msg": "Field required",
                "input": {"username": echoed},
            },
        ]
    }


def test_a_422_without_one_is_answered_as_before(test_client):
    r = _login(test_client, '{"username": "x"}')
    assert (r.status_code, r.headers["content-type"]) == (422, "application/json")
    assert r.content == (
        b'{"detail":[{"type":"missing","loc":["body","password"],'
        b'"msg":"Field required","input":{"username":"x"}}]}'
    )


def test_without_a_non_finite_number_or_a_lone_surrogate_it_is_fastapis_own():
    # Other non-ASCII text stays as FastAPI writes it, unescaped UTF-8.
    errors = [
        {
            "type": "value_error",
            "loc": ("body", "name"),
            "msg": "Value error, m",
            "input": {
                "a": 1.5,
                "b": [2, "x", None, True, {"c": -0.0}],
                "d": 10**30,
                "e": "ä\U0001f600",
            },
        },
        {"type": "missing", "loc": ("body", "password"), "msg": "Field required", "input": {}},
    ]
    ours = _answer(_validation_error, errors)
    assert ours == _answer(request_validation_exception_handler, errors)
    assert "ä\U0001f600".encode() in ours[1]
