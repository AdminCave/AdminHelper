# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-0684: the JSON routes declare a response model that maps today's answer key for key.

Pydantic drops a key the model does not declare without a word, so (a) the operation's 2xx
schema in the live OpenAPI names the model, and (b) the body over the real route equals what
the producer hands out, for a full row and a sparse one; (c) covers each conditional key."""

import json

import pytest
from fastapi.encoders import jsonable_encoder

from app.modules.connections.models import Connection
from app.modules.servers.models import Server


def _login(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _response_ref(path: str, method: str) -> dict:
    from app.main import app

    op = app.openapi()["paths"][path][method]
    status = next(code for code in op["responses"] if code.startswith("2"))
    return op["responses"][status]["content"]["application/json"]["schema"]


def _ref_name(schema: dict) -> str:
    if schema.get("type") == "array":
        schema = schema["items"]
    return schema["$ref"].rsplit("/", 1)[-1]


@pytest.mark.parametrize(
    ("path", "method", "model"),
    [
        ("/api/connections", "get", "ConnectionOut"),
        ("/api/connections", "post", "ConnectionOut"),
        ("/api/connections/{conn_id}", "put", "ConnectionOut"),
        ("/api/connections/{conn_id}/touch", "post", "ConnectionOut"),
        ("/api/connections/import", "post", "ConnectionImportResult"),
    ],
)
def test_connections_declare_their_response_model(path, method, model):
    assert _ref_name(_response_ref(path, method)) == model


class TestConnectionShape:
    def _expected(self, db, conn_id):
        conn = db.get(Connection, conn_id)
        db.refresh(conn)
        return jsonable_encoder(conn.to_dict())

    def _full(self, db):
        db.add(Server(id="srv-conn-shape", name="shape", hostname="shape.example"))
        db.add(
            Connection(
                id="conn-full",
                name="full",
                kind="ssh",
                host="198.51.100.7",
                port=2222,
                username="ops",
                domain="corp.example",
                key_path="/keys/id_ed25519",
                url="https://shape.example",
                notes="note",
                tags='["prod", "edge"]',
                trust_cert=True,
                last_used="2026-10-29T10:00:00+00:00",
                extra_data=json.dumps({"proxyJump": "jump.example"}),
                server_id="srv-conn-shape",
            )
        )
        db.commit()
        return "conn-full"

    def _sparse(self, db):
        # Every nullable column NULL, as a row written by hand or an old build can hold it.
        db.add(
            Connection(
                id="conn-sparse",
                name="sparse",
                kind="rdp",
                host=None,
                port=None,
                username=None,
                domain=None,
                key_path=None,
                url=None,
                notes=None,
                tags=None,
                trust_cert=None,
                last_used=None,
                extra_data=None,
                server_id=None,
            )
        )
        db.commit()
        return "conn-sparse"

    def test_list_equals_to_dict(self, test_client, db_session, admin_user):
        full, sparse = self._full(db_session), self._sparse(db_session)
        r = test_client.get("/api/connections", headers=_login(test_client))
        assert r.status_code == 200, r.text
        by_id = {c["id"]: c for c in r.json()}
        assert by_id[full] == self._expected(db_session, full)
        assert by_id[sparse] == self._expected(db_session, sparse)

    def test_server_id_and_extras_are_conditional(self, test_client, db_session, admin_user):
        full, sparse = self._full(db_session), self._sparse(db_session)
        by_id = {
            c["id"]: c
            for c in test_client.get("/api/connections", headers=_login(test_client)).json()
        }
        assert by_id[full]["serverId"] == "srv-conn-shape"
        # extra=allow keeps a stored extra field under exclude_unset.
        assert by_id[full]["proxyJump"] == "jump.example"
        assert "serverId" not in by_id[sparse]

    def test_old_row_with_another_kind_and_mixed_tags(self, test_client, db_session, admin_user):
        db_session.add(Connection(id="conn-old", name="old", kind="vnc", tags='[1, "a"]'))
        # Imports before v0.36.0 stored a non-list tags value as it came.
        for i, tags in enumerate(["5", '"x"', "null", '{"a": 1}']):
            db_session.add(Connection(id=f"conn-scalar-{i}", name=f"s{i}", kind="ssh", tags=tags))
        db_session.commit()
        res = test_client.get("/api/connections", headers=_login(test_client))
        assert res.status_code == 200
        by_id = {c["id"]: c for c in res.json()}
        for cid in ["conn-old", *(f"conn-scalar-{i}" for i in range(4))]:
            assert by_id[cid] == self._expected(db_session, cid)

    def test_post_put_touch_equal_to_dict(self, test_client, db_session, admin_user):
        h = _login(test_client)
        created = test_client.post(
            "/api/connections",
            json={"name": "made", "kind": "ssh", "host": "192.0.2.4", "proxyJump": "jump.example"},
            headers=h,
        )
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        assert created.json() == self._expected(db_session, cid)
        assert "serverId" not in created.json()

        updated = test_client.put(f"/api/connections/{cid}", json={"notes": "n"}, headers=h)
        assert updated.status_code == 200, updated.text
        assert updated.json() == self._expected(db_session, cid)

        touched = test_client.post(f"/api/connections/{cid}/touch", headers=h)
        assert touched.status_code == 200, touched.text
        assert touched.json() == self._expected(db_session, cid)

    def test_import_result(self, test_client, db_session, admin_user):
        r = test_client.post(
            "/api/connections/import",
            json={"connections": [{"name": "imp", "kind": "ssh"}], "mode": "merge"},
            headers=_login(test_client),
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"imported": 1, "mode": "merge"}
