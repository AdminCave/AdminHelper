# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rejects a query parameter that the schema declares as a single value but that the
request carries more than once (R-1131). FastAPI reads the last value and goes on, so
`offset=1&offset=2` was a 200 for a request the published schema calls invalid."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError


def _is_array(schema: dict) -> bool:
    return schema.get("type") == "array" or any(
        _is_array(s) for s in schema.get("anyOf", []) + schema.get("oneOf", [])
    )


def _scalar_query_params(app: FastAPI) -> dict[tuple[str, str], frozenset[str]]:
    # Read from app.openapi() rather than FastAPI's internals: it is the schema the
    # client (and the fuzzer) builds requests from, and app.openapi() caches it.
    table = getattr(app.state, "scalar_query_params", None)
    if table is None:
        table = {}
        for path, operations in app.openapi().get("paths", {}).items():
            for method, operation in operations.items():
                table[(path, method.upper())] = frozenset(
                    p["name"]
                    for p in operation.get("parameters", [])
                    if p.get("in") == "query" and not _is_array(p.get("schema", {}))
                )
        app.state.scalar_query_params = table
    return table


def reject_repeated_scalar_query(request: Request) -> None:
    route = request.scope.get("route")
    path = getattr(route, "path_format", None)
    if path is None or not request.query_params:
        return
    scalar = _scalar_query_params(request.app).get((path, request.method), frozenset())
    errors = [
        {
            "type": "value_error",
            "loc": ("query", name),
            "msg": "Value error, expected a single value",
            "input": values,
        }
        for name in scalar
        if len(values := request.query_params.getlist(name)) > 1
    ]
    if errors:
        raise RequestValidationError(sorted(errors, key=lambda e: e["loc"]))
