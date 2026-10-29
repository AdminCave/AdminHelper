# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Error answers with a stable code next to the text.

`detail` stays the text existing clients read (and show); `code` is what a client's
code branches on, so a reworded text never breaks a client. Only errors a client is
meant to react to raise CodedHTTPException; every other HTTPException keeps
FastAPI's {"detail": …} body.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


class CodedHTTPException(HTTPException):
    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


async def coded_http_exception_handler(request: Request, exc: CodedHTTPException) -> JSONResponse:
    return JSONResponse(
        {"detail": exc.detail, "code": exc.code},
        status_code=exc.status_code,
        headers=exc.headers,
    )


def install_coded_errors(app: FastAPI) -> None:
    """Answer a CodedHTTPException with {detail, code}.

    Starlette looks the handler up along the exception's MRO, so this one only
    catches the subclass; a plain HTTPException stays with the default handler."""
    app.add_exception_handler(CodedHTTPException, coded_http_exception_handler)
