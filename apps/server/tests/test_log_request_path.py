# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A warning that names the request path escapes control characters in it.

`request.url.path` is percent-decoded, so a `%1B` in the URL is a real ESC byte by the
time it reaches a log call, and a client could drive the terminal of whoever tails the log.
(starlette's URL parser drops CR, LF and TAB; the other control characters stay.) The calls
write the path with %r, which escapes it."""

import asyncio
import logging

import pytest
from starlette.requests import Request

import app.core.identity as identity
import app.core.middleware as mw

# Decoded, as request.url.path hands it over: an ESC sequence and a BEL.
FORGED = "/api/x\x1b[2Jfake\x07"


def _request(path: str = FORGED) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("192.0.2.9", 4000),
        }
    )


def _assert_escaped(caplog) -> None:
    records = [r for r in caplog.records if r.levelno >= logging.DEBUG]
    assert records
    for record in records:
        message = record.getMessage()
        assert "\x1b" not in message
        assert "\x07" not in message
        assert "\\x1b" in message


def test_ip_filter_refusal_escapes_the_path(monkeypatch, caplog):
    monkeypatch.setattr(mw, "_ALLOWED_NETWORKS", mw._parse_networks("198.51.100.0/24", "TEST"))

    async def call_next(_request):
        raise AssertionError("a refused IP must not reach the app")

    with caplog.at_level(logging.WARNING, logger=mw.logger.name):
        response = asyncio.run(mw.IPFilterMiddleware(app=None).dispatch(_request(), call_next))

    assert response.status_code == 403
    _assert_escaped(caplog)


@pytest.mark.parametrize("verified", [True, False])
def test_permissive_scope_check_escapes_the_path(monkeypatch, caplog, verified):
    monkeypatch.setattr(identity.config, "MTLS_ENFORCE", False)
    client = identity.ClientIdentity(verified=verified, cn="x", scope="agent" if verified else None)

    with caplog.at_level(logging.DEBUG, logger=identity.logger.name):
        identity.check_scope(_request(), client, db=None, allowed=frozenset({"admin"}))

    _assert_escaped(caplog)


def test_refused_certificate_escapes_the_path(caplog):
    client = identity.ClientIdentity(verified=True, cn="x", scope="admin")

    with caplog.at_level(logging.WARNING, logger=identity.logger.name):
        with pytest.raises(Exception):
            identity._deny_refused(_request(), client)

    _assert_escaped(caplog)
