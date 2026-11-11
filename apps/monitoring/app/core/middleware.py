# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The NUL guard for path and query string — a copy of the server's
NulByteMiddleware (apps/server/app/core/middleware.py): monitoring is its own
service and shares no code with the server. And the size bound of an agent report."""

import re

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def _nul_rejected(loc: list[str], value: str) -> JSONResponse:
    # The fields of FastAPI's own 422 that a client reads (type, loc, msg, input),
    # so it parses one format whether the NUL was caught here or by a validator.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "type": "value_error",
                    "loc": loc,
                    "msg": "Value error, must not contain a NUL byte",
                    "input": value,
                }
            ]
        },
    )


class NulByteMiddleware(BaseHTTPMiddleware):
    """Answers 422 when the path or the query string carries a NUL byte.

    Postgres stores no 0x00 in a text value, so a NUL that reaches a str path or
    query parameter dies in the driver while binding — HTTP 500. Checked here,
    before routing, on scope["path"] and the parsed query parameters, both
    percent-decoded once. A JSON body is out of reach here: its NUL is spelled
    \\u0000 and only exists once the body is parsed (RequestModel does that)."""

    async def dispatch(self, request: Request, call_next):
        path = request.scope["path"]
        if "\x00" in path:
            return _nul_rejected(["path"], path)
        for name, value in request.query_params.multi_items():
            if "\x00" in name:
                return _nul_rejected(["query", name], name)
            if "\x00" in value:
                return _nul_rejected(["query", name], value)
        return await call_next(request)


# The gateway's client_max_body_size (apps/gateway); the service bounds the report
# itself, so a caller inside the compose network meets the same limit.
REPORT_BODY_LIMIT = 10 * 1024 * 1024
_REPORT_PATH = re.compile(r"/agent/[^/]+/report")
_TOO_LARGE = "Agent report exceeds the size limit"


class ReportBodyLimitMiddleware:
    """Answers 413 when an agent report carries more than REPORT_BODY_LIMIT bytes.

    Pure ASGI: the body is counted while the route reads it, so a request without
    a Content-Length (chunked) is cut off at the limit instead of being held whole."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not _REPORT_PATH.fullmatch(scope["path"])
        ):
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > REPORT_BODY_LIMIT):
            await JSONResponse(status_code=413, content={"detail": _TOO_LARGE})(
                scope, receive, send
            )
            return
        seen = 0

        async def bounded_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > REPORT_BODY_LIMIT:
                    # FastAPI passes an HTTPException from reading the body on as it is
                    # (any other error there becomes a 400).
                    raise HTTPException(status_code=413, detail=_TOO_LARGE)
            return message

        await self.app(scope, bounded_receive, send)
