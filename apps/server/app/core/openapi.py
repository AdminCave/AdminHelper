# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The published OpenAPI schema, with the BIGINT bounds as exact integers.

FastAPI types `maximum`/`minimum` as float, and past 2**53 a float no longer holds
every integer: the BIGINT maximum of a request body comes out as
9.223372036854776e+18, which a client reading the JSON number takes as a limit
193 above the real one. The runtime check is unaffected (pydantic keeps the int);
this only corrects what the schema publishes, by the pattern of FastAPI's
"Extending OpenAPI": generate, adjust, keep the result.
"""

from typing import Any

from fastapi import FastAPI

from app.core.bounds import BIGINT_MAX

_EXACT = {float(BIGINT_MAX): BIGINT_MAX, float(-BIGINT_MAX - 1): -BIGINT_MAX - 1}


def _exact_int_bounds(node: Any) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("maximum", "minimum") and isinstance(value, float) and value in _EXACT:
                node[key] = _EXACT[value]
            else:
                _exact_int_bounds(value)
    elif isinstance(node, list):
        for item in node:
            _exact_int_bounds(item)


def install_exact_int_bounds(app: FastAPI) -> None:
    """Serve app.openapi() with the exact BIGINT bounds.

    FastAPI.openapi generates the schema once and keeps it on the app (again only
    when the routes change); each schema it hands out is corrected once, in place.
    """
    corrected: list[dict[str, Any]] = []

    def openapi() -> dict[str, Any]:
        schema = FastAPI.openapi(app)
        if not corrected or corrected[0] is not schema:
            _exact_int_bounds(schema)
            corrected[:] = [schema]
        return schema

    app.openapi = openapi
