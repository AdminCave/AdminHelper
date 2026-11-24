# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The NUL guard for path and query string, the same in the server and the monitoring."""

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
    query parameter dies in the driver while binding — HTTP 500. Those parameters
    are function arguments, not models, and guarding them one by one never ends;
    so the check sits here, before routing. It reads scope["path"] and the parsed
    query parameters, both percent-decoded once — raw_path and the raw query
    string still spell the byte `%00`. Before routing the path has no field
    names yet, so its loc is just ["path"].

    A JSON body is out of reach here: its NUL is spelled \\u0000 and only exists
    once the body is parsed."""

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
