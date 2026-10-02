# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every integer the API accepts carries an upper bound in the published schema.

An integer without `maximum` lets a client send 2**63 and more; in the server and in
monitoring such a value reached SQL OFFSET or an INTEGER column and failed there
(OverflowError, NumericValueOutOfRange) before a response existed. The fuzz gate used to find that
class at random in its generate phase; since the PR gate runs the explicit phase only,
this lint finds it deterministically: parameters and request bodies, `$ref` resolved,
through `anyOf`/`oneOf`/`allOf`, `items` and `additionalProperties`.
"""

import pytest

_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}


def _unbounded_integers(spec: dict) -> list[str]:
    schemas = spec.get("components", {}).get("schemas", {})
    found: set[str] = set()

    def walk(node, where: str, seen: frozenset) -> None:
        if not isinstance(node, dict):
            return
        ref = node.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            if name not in seen:
                walk(schemas.get(name, {}), where, seen | {name})
            return
        if node.get("type") == "integer" and not {"maximum", "exclusiveMaximum"} & node.keys():
            found.add(where)
        for prop, sub in (node.get("properties") or {}).items():
            walk(sub, f"{where}.{prop}", seen)
        for key in ("anyOf", "oneOf", "allOf"):
            for sub in node.get(key) or []:
                walk(sub, where, seen)
        walk(node.get("items"), f"{where}[]", seen)
        walk(node.get("additionalProperties"), f"{where}{{}}", seen)

    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method not in _METHODS:
                continue
            for param in [*item.get("parameters", []), *op.get("parameters", [])]:
                walk(
                    param.get("schema"),
                    f"{method.upper()} {path} {param['in']}:{param['name']}",
                    frozenset(),
                )
            for content in (op.get("requestBody") or {}).get("content", {}).values():
                walk(content.get("schema"), f"{method.upper()} {path} body", frozenset())
    return sorted(found)


def test_every_integer_input_has_a_maximum():
    from app.main import app

    unbounded = _unbounded_integers(app.openapi())
    assert unbounded == [], "integer inputs without maximum:\n  " + "\n  ".join(unbounded)


def test_the_lint_sees_an_unbounded_integer():
    # Without this the lint above would pass just as well for a walker that never
    # reaches a field: a body by $ref, an optional field in anyOf, a list item.
    spec = {
        "paths": {
            "/x": {
                "parameters": [{"in": "path", "name": "p", "schema": {"type": "integer"}}],
                "post": {
                    "parameters": [{"in": "query", "name": "n", "schema": {"type": "integer"}}],
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/B"}}
                        }
                    },
                },
            }
        },
        "components": {
            "schemas": {
                "B": {
                    "properties": {
                        "a": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                        "b": {"type": "array", "items": {"type": "integer", "maximum": 6}},
                        "c": {"type": "array", "items": {"type": "integer"}},
                        "d": {"type": "integer", "exclusiveMaximum": 10},
                        "e": {"allOf": [{"$ref": "#/components/schemas/C"}]},
                        "f": {"type": "object", "additionalProperties": {"type": "integer"}},
                    }
                },
                "C": {"properties": {"g": {"type": "integer"}}},
            }
        },
    }
    assert _unbounded_integers(spec) == [
        "POST /x body.a",
        "POST /x body.c[]",
        "POST /x body.e.g",
        "POST /x body.f{}",
        "POST /x path:p",
        "POST /x query:n",
    ]


_PING = {"name": "c", "check_type": "ping", "config": {"target": "127.0.0.1"}}
_WEEKLY = {"kind": "weekly", "weekdays": [6], "start_time": "02:00", "duration_minutes": 120}


@pytest.mark.parametrize(
    "path,body",
    [
        ("/alerts", {"name": "r", "channel": "webhook", "cooldown_minutes": 2**31}),
        ("/checks", {**_PING, "consecutive_fails": 2**31}),
        ("/maintenance", {**_WEEKLY, "duration_minutes": 2**31}),
        ("/maintenance", {**_WEEKLY, "weekdays": [7]}),
    ],
)
def test_values_past_the_bounds_are_a_422(client_db, path, body):
    # The INTEGER columns end at 2**31 - 1 and a weekday at 6; past that the boundary
    # answers 422 instead of handing the value to the database.
    client, _ = client_db
    assert client.post(path, json=body).status_code == 422
