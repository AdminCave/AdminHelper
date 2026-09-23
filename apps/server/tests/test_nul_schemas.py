# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every request schema inherits RequestModel, so a NUL in any body field is a 422.

Until this change a NUL was refused only where SafeText sat — the fields a fuzz
run had caught. The routes below are the ones tests/schemathesis_exclude.toml
held open for exactly that reason; each died in the driver with DataError, and
the client got HTTP 500. The structural test makes the rule hold for a schema
nobody has written yet."""

import pytest
from pydantic import BaseModel

from app.core.bounds import RequestModel
from app.main import app

NUL = chr(0)


def _refs(node) -> set[str]:
    if isinstance(node, dict):
        found = {node["$ref"].rsplit("/", 1)[-1]} if "$ref" in node else set()
        for value in node.values():
            found |= _refs(value)
        return found
    if isinstance(node, list):
        return set().union(*(_refs(item) for item in node)) if node else set()
    return set()


def _request_schema_names() -> set[str]:
    """Every component a request body reaches, nested ones included."""
    spec = app.openapi()
    components = spec["components"]["schemas"]
    todo = set()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if "requestBody" not in operation:
                continue
            body = _refs(operation["requestBody"])
            # A body that is not a model (a bare dict or list) has no $ref and
            # would pass this test unseen — it needs a rule of its own.
            assert body, f"{method.upper()} {path}: request body is not a model"
            todo |= body
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo |= _refs(components[name]) - seen
    return seen


def _models_by_name() -> dict[str, list[type[BaseModel]]]:
    found: dict[str, list[type[BaseModel]]] = {}
    todo = [BaseModel]
    while todo:
        for sub in todo.pop().__subclasses__():
            todo.append(sub)
            if sub.__module__.startswith("app.") and sub not in found.get(sub.__name__, []):
                found.setdefault(sub.__name__, []).append(sub)
    return found


def test_every_request_schema_inherits_request_model():
    names = _request_schema_names()
    # The instrument has to find something, or an empty set would pass: one
    # top-level body and one that is only reachable nested inside another.
    assert {"ServerCreate", "SubscriptionInput"} <= names
    models = _models_by_name()
    # One class per name, or the check below could look at the wrong one.
    assert sorted(n for n in names if len(models.get(n, [])) != 1) == []
    assert sorted(n for n in names if not issubclass(models[n][0], RequestModel)) == []


def _login(test_client) -> dict:
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_TUNNEL = {
    "server_id": "ghost",
    "frp_config_id": "ghost",
    "name": "t1",
    "tunnel_type": "stcp",
    "protocol": "ssh",
    "local_port": 22,
}
_PLAYBOOK = {"name": "p1", "filename": "p1.yml", "content": "- hosts: all\n"}

# (method, path, clean body, field that gets the NUL, status of the clean body)
CASES = [
    ("post", "/api/servers", {"name": "s1", "hostname": "h1"}, "hostname", 201),
    ("post", "/api/servers", {"name": "s1", "hostname": "h1", "notes": "n"}, "notes", 201),
    ("post", "/api/ansible/playbooks", _PLAYBOOK, "name", 201),
    ("post", "/api/ansible/playbooks", {**_PLAYBOOK, "description": "d"}, "description", 201),
    ("post", "/api/connections", {"name": "c1", "kind": "ssh", "host": "h"}, "host", 201),
    ("post", "/api/connections", {"name": "c1", "kind": "ssh", "notes": "n"}, "notes", 201),
    ("post", "/api/frp/tunnels", _TUNNEL, "server_id", 404),
]


@pytest.mark.parametrize(("method", "path", "body", "field", "clean_status"), CASES)
def test_a_nul_in_a_body_field_is_422(
    method, path, body, field, clean_status, test_client, db_session, admin_user
):
    headers = _login(test_client)
    send = getattr(test_client, method)

    # The clean body gets past validation — the 422 below is the NUL's, not a
    # missing field's.
    ok = send(path, json=body, headers=headers)
    assert ok.status_code == clean_status, f"{path} {field}: {ok.status_code} {ok.text}"

    nul = send(path, json={**body, field: "a" + NUL + "b"}, headers=headers)
    assert nul.status_code == 422, f"{path} {field}: {nul.status_code} {nul.text}"
    assert nul.json()["detail"][0]["loc"] == ["body", field]
