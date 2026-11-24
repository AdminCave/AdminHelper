# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The size bound of an agent report. The NUL guard comes from ah_common.middleware."""

import re

from fastapi import HTTPException
from starlette.responses import JSONResponse

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
