# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Server-bound API keys across every route that accepts a key (ApiKeyOrUser).

A key can be bound to one server (api_keys.server_id). The matrix below pins what
each kind of key may do on each key route — read, write and the FRP provisioning —
sent as X-API-Key header and as ?api_key=. The guard at the end keeps the matrix
complete: the routes that accept a key must be exactly the routes in the matrix,
so a new key route has to state here what a bound key may do on it.
"""

import pytest

from app.core.auth import hash_api_key
from app.modules.api_keys.models import ApiKey
from app.modules.connections.models import Connection
from app.modules.servers.models import Server

from .test_route_auth_gate import _api_methods, _collect_api_routes, _dependency_qualnames

_KEYS = {
    # name: (permission, server_id)
    "bound_read": ("read", "srv-a"),
    "bound_rw": ("read_write", "srv-a"),
    "global_read": ("read", None),
    "global_rw": ("read_write", None),
}


def _raw(name: str) -> str:
    return f"ah_matrix_{name}"


def _seed(db) -> None:
    db.add(Server(id="srv-a", name="server-a", hostname="a.example.test"))
    db.add(Server(id="srv-b", name="server-b", hostname="b.example.test"))
    db.flush()  # the servers first: keys and connections reference them by foreign key only
    for cid, sid in (("c-a", "srv-a"), ("c-b", "srv-b"), ("c-null", None)):
        db.add(Connection(id=cid, name=f"conn-{cid}", kind="ssh", host="h", port=22, server_id=sid))
    for name, (permission, sid) in _KEYS.items():
        db.add(
            ApiKey(
                name=name, hashed_key=hash_api_key(_raw(name)), permission=permission, server_id=sid
            )
        )
    db.commit()


def _state(db) -> list[dict]:
    db.expire_all()
    return sorted((c.to_dict() for c in db.query(Connection).all()), key=lambda c: c["id"])


def _send(client, method: str, path: str, key: str, via: str, body):
    raw = _raw(key)
    if via == "header":
        return client.request(method, path, headers={"X-API-Key": raw}, json=body)
    return client.request(method, f"{path}?api_key={raw}", json=body)


def _new(server_id="omit") -> dict:
    body = {"name": "neu", "kind": "ssh", "host": "h", "port": 22}
    if server_id != "omit":
        body["serverId"] = server_id
    return body


_LIST = ("GET", "/api/connections")
_TOUCH = ("POST", "/api/connections/{conn_id}/touch")
_CREATE = ("POST", "/api/connections")
_UPDATE = ("PUT", "/api/connections/{conn_id}")
_FRP_CONFIG = ("GET", "/api/frp/provision/{server_id}/config")
_FRP_HASH = ("GET", "/api/frp/provision/{server_id}/config-hash")

# (route, concrete path, key, body, expected status)
MATRIX = [
    # Reading: a bound key sees and touches only its own server's connections.
    (_LIST, "/api/connections", "bound_read", None, 200),
    (_LIST, "/api/connections", "bound_rw", None, 200),
    (_LIST, "/api/connections", "global_read", None, 200),
    (_TOUCH, "/api/connections/c-a/touch", "bound_read", None, 200),
    (_TOUCH, "/api/connections/c-a/touch", "bound_rw", None, 200),
    (_TOUCH, "/api/connections/c-b/touch", "bound_read", None, 404),
    (_TOUCH, "/api/connections/c-b/touch", "bound_rw", None, 404),
    (_TOUCH, "/api/connections/c-null/touch", "bound_read", None, 404),
    (_TOUCH, "/api/connections/c-null/touch", "bound_rw", None, 404),
    (_TOUCH, "/api/connections/c-b/touch", "global_read", None, 200),
    # Writing needs a read_write key.
    (_CREATE, "/api/connections", "bound_read", _new("srv-a"), 403),
    (_CREATE, "/api/connections", "global_read", _new(None), 403),
    (_UPDATE, "/api/connections/c-a", "bound_read", {"name": "x"}, 403),
    # A bound read_write key writes only for its own server.
    (_CREATE, "/api/connections", "bound_rw", _new("srv-a"), 201),
    (_CREATE, "/api/connections", "bound_rw", _new("srv-b"), 403),
    (_CREATE, "/api/connections", "bound_rw", _new(None), 403),
    (_CREATE, "/api/connections", "bound_rw", _new(), 403),
    (_UPDATE, "/api/connections/c-a", "bound_rw", {"serverId": "srv-a"}, 200),
    (_UPDATE, "/api/connections/c-a", "bound_rw", {"name": "renamed"}, 200),
    (_UPDATE, "/api/connections/c-a", "bound_rw", {"serverId": "srv-b"}, 403),
    (_UPDATE, "/api/connections/c-a", "bound_rw", {"serverId": None}, 403),
    # A foreign serverId is refused before its existence is looked at: the same 403
    # for a server that does not exist as for one that does.
    (_CREATE, "/api/connections", "bound_rw", _new("srv-missing"), 403),
    (_UPDATE, "/api/connections/c-a", "bound_rw", {"serverId": "srv-missing"}, 403),
    # Only the camelCase spelling is accepted, so serverId is the only name that
    # sets the column.
    (_CREATE, "/api/connections", "bound_rw", {**_new("srv-a"), "server_id": "srv-b"}, 422),
    (_UPDATE, "/api/connections/c-a", "bound_rw", {"server_id": "srv-b"}, 422),
    (_UPDATE, "/api/connections/c-b", "bound_rw", {"name": "x"}, 404),
    (_UPDATE, "/api/connections/c-null", "bound_rw", {"serverId": "srv-a"}, 404),
    # A key without a binding writes for any server, and for none.
    (_CREATE, "/api/connections", "global_rw", _new("srv-b"), 201),
    (_CREATE, "/api/connections", "global_rw", _new(), 201),
    (_UPDATE, "/api/connections/c-b", "global_rw", {"serverId": "srv-a"}, 200),
    # FRP provisioning of a foreign server, for both permissions.
    (_FRP_CONFIG, "/api/frp/provision/srv-b/config", "bound_read", None, 403),
    (_FRP_CONFIG, "/api/frp/provision/srv-b/config", "bound_rw", None, 403),
    (_FRP_HASH, "/api/frp/provision/srv-b/config-hash", "bound_read", None, 403),
    (_FRP_HASH, "/api/frp/provision/srv-b/config-hash", "bound_rw", None, 403),
]


@pytest.mark.parametrize("via", ["header", "query"])
@pytest.mark.parametrize(
    "route,path,key,body,expected",
    MATRIX,
    ids=[f"{r[0][0]} {r[1]} {r[2]} {r[3]}" for r in MATRIX],
)
def test_key_route_matrix(test_client, db_session, route, path, key, body, expected, via):
    _seed(db_session)
    before = _state(db_session)
    r = _send(test_client, route[0], path, key, via, body)
    assert r.status_code == expected, r.text
    if route in (_CREATE, _UPDATE) and expected >= 400:
        assert _state(db_session) == before, "a refused write must not change anything"


@pytest.mark.parametrize("via", ["header", "query"])
@pytest.mark.parametrize(
    "key,visible",
    [
        ("bound_read", {"c-a"}),
        ("bound_rw", {"c-a"}),
        ("global_read", {"c-a", "c-b", "c-null"}),
    ],
)
def test_list_shows_only_what_the_key_may_see(test_client, db_session, key, visible, via):
    _seed(db_session)
    r = _send(test_client, "GET", "/api/connections", key, via, None)
    assert r.status_code == 200, r.text
    assert {c["id"] for c in r.json()} == visible


@pytest.mark.parametrize("via", ["header", "query"])
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("DELETE", "/api/connections/c-a", None),
        ("GET", "/api/connections/export", None),
        ("POST", "/api/connections/import", {"connections": [], "mode": "merge"}),
    ],
)
def test_admin_routes_do_not_accept_a_key(test_client, db_session, method, path, body, via):
    _seed(db_session)
    before = _state(db_session)
    r = _send(test_client, method, path, "bound_rw", via, body)
    assert r.status_code == 401, r.text
    assert _state(db_session) == before


def test_the_matrix_covers_every_key_route():
    from app.main import app

    key_routes = {
        (method, path)
        for method, path, route in _api_methods(_collect_api_routes(app))
        if any("ApiKeyOrUser" in q for q in _dependency_qualnames(route))
    }
    assert key_routes, "no route accepts an API key: the route walker found nothing"
    assert key_routes == {row[0] for row in MATRIX}
