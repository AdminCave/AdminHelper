# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The 422 of both services: FastAPI's own, unless the input it echoes cannot be written as
JSON. Each app registers it with ``app.add_exception_handler(RequestValidationError,
validation_error)``."""

import json
import math

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response


def _non_finite_as_null(detail: list) -> list:
    """`detail` with every non-finite float set to None, in place: it is the output of
    jsonable_encoder, so fresh dicts, lists and scalars only. Walks with an explicit
    stack, since the input it echoes is whatever the client nested."""
    stack: list = [detail]
    while stack:
        node = stack.pop()
        for key in list(node.keys() if isinstance(node, dict) else range(len(node))):
            value = node[key]
            if isinstance(value, float) and not math.isfinite(value):
                node[key] = None
            elif isinstance(value, (dict, list)):
                stack.append(value)
    return detail


async def validation_error(request: Request, exc: RequestValidationError) -> Response:
    """FastAPI's 422. The input it echoes may hold a non-finite number: json.loads reads the
    tokens Infinity and NaN, and JSONResponse refuses to write them back, which was a 500. It
    may also hold a lone surrogate (JSON spells one as \\ud800), which has no UTF-8 form; that
    is a UnicodeEncodeError, a ValueError too. That answer gives such a number as null and
    escapes every non-ASCII character, as JSON allows; every other 422 is FastAPI's own."""
    try:
        return await request_validation_exception_handler(request, exc)
    except ValueError:
        detail = _non_finite_as_null(jsonable_encoder(exc.errors()))
        content = json.dumps({"detail": detail}, allow_nan=False, separators=(",", ":"))
        return Response(content, status_code=422, media_type="application/json")
