# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-0684: the JSON routes declare a response model that maps today's answer key for key.

Pydantic drops a key the model does not declare without a word, so (a) the operation's 2xx
schema in the live OpenAPI names the model, and (b) the body over the real route equals what
the producer hands out, for a full row and a sparse one; (c) covers each conditional key."""

import datetime
import json
import secrets
import uuid

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import update

from app.core.auth import hash_api_key
from app.modules.ansible.models import Playbook
from app.modules.connections.models import Connection
from app.modules.frp import tunnel_router
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.notifications.models import Notification, NotificationSubscription
from app.modules.provisioning import router as provisioning_router
from app.modules.provisioning.models import ProvisionToken
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
        ("/api/servers", "get", "ServerOut"),
        ("/api/servers", "post", "ServerOut"),
        ("/api/servers/{server_id}", "get", "ServerOut"),
        ("/api/servers/{server_id}", "put", "ServerOut"),
        ("/api/internal/servers", "get", "InternalServerOut"),
        ("/api/frp/tunnels", "post", "FrpTunnelOut"),
        ("/api/frp/tunnels/{tunnel_id}", "get", "FrpTunnelOut"),
        ("/api/frp/tunnels/{tunnel_id}", "put", "FrpTunnelOut"),
        ("/api/ansible/playbooks", "get", "PlaybookOut"),
        ("/api/ansible/playbooks", "post", "PlaybookOut"),
        ("/api/ansible/playbooks/{playbook_id}", "get", "PlaybookOut"),
        ("/api/ansible/playbooks/{playbook_id}", "put", "PlaybookOut"),
        ("/api/ansible/playbooks/{playbook_id}/content", "get", "PlaybookContentOut"),
        ("/api/servers/{server_id}/provision/token", "post", "ProvisionTokenCreatedOut"),
        ("/api/servers/{server_id}/provision/tokens", "get", "ProvisionTokenOut"),
        ("/api/servers/{server_id}/provision/activate", "post", "ActivateOut"),
        ("/api/notifications", "get", "NotificationOut"),
        ("/api/notifications/unread-count", "get", "UnreadCountOut"),
        ("/api/notifications/read", "post", "MarkReadOut"),
        ("/api/users/me/notification-prefs", "get", "NotificationPrefsOut"),
        ("/api/users/me/notification-prefs", "put", "NotificationPrefsOut"),
        ("/api/internal/events", "post", "EventsAcceptedOut"),
    ],
)
def test_routes_declare_their_response_model(path, method, model):
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


class TestServerShape:
    def _expected(self, db, server_id):
        server = db.get(Server, server_id)
        db.refresh(server)
        return jsonable_encoder(server.to_dict())

    def _full(self, db):
        db.add(
            FrpServerConfig(
                id="cfg-shape",
                name="shape",
                server_addr="frps.example",
                bind_port=7000,
                auth_token="frps-auth-token-value",
            )
        )
        db.add(
            Server(
                id="srv-full",
                name="full",
                hostname="full.example",
                os_type="linux",
                tags='["prod"]',
                notes="note",
            )
        )
        db.add(Connection(id="conn-of-full", name="ssh", kind="ssh", server_id="srv-full"))
        db.add(
            FrpTunnel(
                id="t-shape",
                server_id="srv-full",
                frp_config_id="cfg-shape",
                name="full-ssh",
                tunnel_type="stcp",
                protocol="ssh",
                local_port=22,
                secret_key="tunnel-secret-value",
                visitor_port=6001,
                extra_config=json.dumps({"transport.useEncryption": True}),
                tags='["edge"]',
                enabled=True,
            )
        )
        db.commit()
        return "srv-full"

    def _sparse(self, db):
        db.add(Server(id="srv-sparse", name="sparse", hostname="sparse.example"))
        db.commit()
        return "srv-sparse"

    def test_list_and_get_equal_to_dict(self, test_client, db_session, admin_user):
        full, sparse = self._full(db_session), self._sparse(db_session)
        h = _login(test_client)
        r = test_client.get("/api/servers", headers=h)
        assert r.status_code == 200, r.text
        by_id = {s["id"]: s for s in r.json()}
        for sid in (full, sparse):
            assert by_id[sid] == self._expected(db_session, sid)
            assert test_client.get(f"/api/servers/{sid}", headers=h).json() == self._expected(
                db_session, sid
            )
        # The nested connection keeps its serverId, the tunnel its masked secret.
        assert by_id[full]["connections"][0]["serverId"] == full
        assert by_id[full]["frpTunnels"][0]["secretKey"] is None
        assert by_id[sparse]["osType"] is None
        assert by_id[sparse]["connections"] == [] and by_id[sparse]["frpTunnels"] == []

    def test_post_put_equal_to_dict(self, test_client, db_session, admin_user):
        h = _login(test_client)
        created = test_client.post(
            "/api/servers", json={"name": "made", "hostname": "made.example"}, headers=h
        )
        assert created.status_code == 201, created.text
        sid = created.json()["id"]
        assert created.json() == self._expected(db_session, sid)
        updated = test_client.put(f"/api/servers/{sid}", json={"tags": ["a"]}, headers=h)
        assert updated.status_code == 200, updated.text
        assert updated.json() == self._expected(db_session, sid)

    def test_internal_listing(self, test_client, db_session, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "right")
        self._full(db_session)
        r = test_client.get("/api/internal/servers", headers={"X-Internal-Key": "right"})
        assert r.status_code == 200, r.text
        assert r.json() == [
            {"id": "srv-full", "hostname": "full.example", "name": "full", "tags": ["prod"]}
        ]


def test_tunnel_list_declares_both_shapes():
    items = _response_ref("/api/frp/tunnels", "get")["items"]
    assert [ref["$ref"].rsplit("/", 1)[-1] for ref in items["anyOf"]] == [
        "FrpTunnelOut",
        "TunnelMappingOut",
    ]


class TestTunnelShape:
    """The admin reads FrpTunnel.to_dict(mask_secrets=True), a non-admin the mapping keys."""

    def _seed(self, db):
        db.add(
            FrpServerConfig(
                id="cfg-t",
                name="t",
                server_addr="frps.example",
                bind_port=7000,
                auth_token="frps-auth-token-value",
            )
        )
        db.add(Server(id="srv-t", name="t", hostname="t.example"))
        db.add(
            FrpTunnel(
                id="t-full",
                server_id="srv-t",
                frp_config_id="cfg-t",
                name="a-full",
                tunnel_type="https",
                protocol="web",
                local_ip="127.0.0.1",
                local_port=443,
                secret_key="tunnel-secret-value",
                custom_domains="web.example",
                extra_config=json.dumps({"transport.useEncryption": True}),
                tags='["edge"]',
                enabled=True,
            )
        )
        db.add(
            FrpTunnel(
                id="t-sparse",
                server_id="srv-t",
                frp_config_id="cfg-t",
                name="b-sparse",
                tunnel_type="stcp",
                protocol="ssh",
                local_ip=None,
                local_port=22,
                enabled=True,
            )
        )
        db.commit()

    def _expected(self, db, tunnel_id):
        tunnel = db.get(FrpTunnel, tunnel_id)
        db.refresh(tunnel)
        return jsonable_encoder(tunnel.to_dict(mask_secrets=True))

    def test_admin_list_and_get_equal_to_dict(self, test_client, db_session, admin_user):
        self._seed(db_session)
        h = _login(test_client)
        r = test_client.get("/api/frp/tunnels", headers=h)
        assert r.status_code == 200, r.text
        want = [self._expected(db_session, t) for t in ("t-full", "t-sparse")]
        assert r.json() == want
        assert all(t["secretKey"] is None for t in r.json())
        for tid, row in zip(("t-full", "t-sparse"), want):
            got = test_client.get(f"/api/frp/tunnels/{tid}", headers=h)
            assert got.status_code == 200, got.text
            assert got.json() == row

    def test_non_admin_list_keeps_the_mapping_shape(self, test_client, db_session, normal_user):
        self._seed(db_session)
        normal_user.servers.append(db_session.get(Server, "srv-t"))
        db_session.commit()
        r = test_client.post(
            "/api/auth/login", json={"username": "viewer", "password": "viewerpass"}
        )
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = test_client.get("/api/frp/tunnels", headers=h)
        assert r.status_code == 200, r.text
        keys = tunnel_router._MAPPING_FIELDS
        assert r.json() == [
            {k: self._expected(db_session, t)[k] for k in keys} for t in ("t-full", "t-sparse")
        ]

    def test_post_put_equal_to_dict(self, test_client, db_session, admin_user):
        self._seed(db_session)
        h = _login(test_client)
        body = {
            "server_id": "srv-t",
            "frp_config_id": "cfg-t",
            "name": "made",
            "tunnel_type": "stcp",
            "protocol": "ssh",
            "local_port": 22,
        }
        created = test_client.post("/api/frp/tunnels", json=body, headers=h)
        assert created.status_code == 201, created.text
        tid = created.json()["id"]
        assert created.json() == self._expected(db_session, tid)
        assert created.json()["secretKey"] is None
        updated = test_client.put(f"/api/frp/tunnels/{tid}", json={"tags": ["x"]}, headers=h)
        assert updated.status_code == 200, updated.text
        assert updated.json() == self._expected(db_session, tid)


class TestPlaybookShape:
    def _expected(self, db, playbook_id):
        playbook = db.get(Playbook, playbook_id)
        db.refresh(playbook)
        return jsonable_encoder(playbook.to_dict())

    def test_list_and_get_equal_to_dict(self, test_client, db_session, admin_user):
        db_session.add(
            Playbook(
                id="pb-full",
                name="full",
                filename="full.yml",
                description="desc",
                tags='["web", "db"]',
            )
        )
        # NULL description and tags: to_dict hands out "" and [].
        db_session.add(Playbook(id="pb-sparse", name="sparse", filename="sparse.yaml"))
        db_session.commit()
        h = _login(test_client)
        r = test_client.get("/api/ansible/playbooks", headers=h)
        assert r.status_code == 200, r.text
        by_id = {p["id"]: p for p in r.json()}
        for pid in ("pb-full", "pb-sparse"):
            assert by_id[pid] == self._expected(db_session, pid)
            got = test_client.get(f"/api/ansible/playbooks/{pid}", headers=h)
            assert got.status_code == 200, got.text
            assert got.json() == self._expected(db_session, pid)
        assert by_id["pb-sparse"]["description"] == "" and by_id["pb-sparse"]["tags"] == []
        assert by_id["pb-sparse"]["updatedAt"] is None

    def test_post_content_put_equal_to_dict(self, test_client, db_session, admin_user):
        h = _login(test_client)
        body = {"name": "made", "filename": "made.yml", "tags": ["x"], "content": "- hosts: all\n"}
        created = test_client.post("/api/ansible/playbooks", json=body, headers=h)
        assert created.status_code == 201, created.text
        pid = created.json()["id"]
        assert created.json() == self._expected(db_session, pid)

        content = test_client.get(f"/api/ansible/playbooks/{pid}/content", headers=h)
        assert content.status_code == 200, content.text
        assert content.json() == {"content": "- hosts: all\n"}

        updated = test_client.put(
            f"/api/ansible/playbooks/{pid}", json={"description": "changed"}, headers=h
        )
        assert updated.status_code == 200, updated.text
        assert updated.json() == self._expected(db_session, pid)
        test_client.delete(f"/api/ansible/playbooks/{pid}", headers=h)


class TestProvisioningShape:
    def _server(self, db) -> str:
        db.add(Server(id="srv-prov", name="prov", hostname="prov.example"))
        db.commit()
        return "srv-prov"

    def _token(self, db, server_id: str) -> str:
        raw = f"adminhelper_prov_{secrets.token_urlsafe(16)}"
        db.add(
            ProvisionToken(
                id=str(uuid.uuid4()),
                server_id=server_id,
                hashed_token=hash_api_key(raw),
                expires_at=datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(hours=24),
            )
        )
        db.commit()
        return raw

    def _activate(self, client, server_id: str, raw: str) -> dict:
        r = client.post(
            f"/api/servers/{server_id}/provision/activate", headers={"X-Provision-Token": raw}
        )
        assert r.status_code == 200, r.text
        return r.json()

    def test_token_create_and_list_equal_to_dict(self, test_client, db_session, admin_user):
        sid = self._server(db_session)
        h = _login(test_client)
        created = test_client.post(f"/api/servers/{sid}/provision/token", headers=h)
        assert created.status_code == 200, created.text
        body = created.json()
        assert set(body) == {"token", "expiresAt", "serverId", "serverName"}
        assert body["serverId"] == sid and body["serverName"] == "prov"
        assert hash_api_key(body["token"]) == db_session.query(ProvisionToken).one().hashed_token

        # A spent token next to the fresh one: usedAt set, isValid false.
        self._token(db_session, sid)
        spent = db_session.query(ProvisionToken).order_by(ProvisionToken.created_at).all()[-1]
        db_session.execute(
            update(ProvisionToken)
            .where(ProvisionToken.id == spent.id)
            .values(used_at=datetime.datetime(2026, 1, 1))
        )
        db_session.commit()
        listed = test_client.get(f"/api/servers/{sid}/provision/tokens", headers=h)
        assert listed.status_code == 200, listed.text
        rows = {t["id"]: t for t in listed.json()}
        assert len(rows) == 2
        for token in db_session.query(ProvisionToken).all():
            db_session.refresh(token)
            assert rows[token.id] == jsonable_encoder(token.to_dict())
        assert rows[spent.id]["usedAt"] is not None and rows[spent.id]["isValid"] is False

    def test_activate_without_monitor_and_frp(self, test_client, db_session):
        sid = self._server(db_session)
        body = self._activate(test_client, sid, self._token(db_session, sid))
        assert set(body) == {
            "serverName",
            "apiKey",
            "monitorApiKey",
            "monitorUrl",
            "frp",
            "enrollment",
        }
        assert body["monitorApiKey"] is None and body["monitorUrl"] is None and body["frp"] is None
        enrollment = body["enrollment"]
        assert set(enrollment) == {"token", "subjectId", "scope", "enrollPort"}
        assert enrollment["subjectId"] == sid and enrollment["scope"] == "tunnel"
        assert isinstance(enrollment["enrollPort"], int)

    def test_activate_with_monitor_and_frp(self, test_client, db_session, monkeypatch):
        monkeypatch.setattr(provisioning_router, "fetch_or_skip_monitor_key", lambda _: "mon-key")
        db_session.add(
            FrpServerConfig(
                id="cfg-prov",
                name="prov",
                server_addr="frps.example",
                bind_port=7000,
                auth_token="frps-auth-token-value",
            )
        )
        sid = self._server(db_session)
        body = self._activate(test_client, sid, self._token(db_session, sid))
        assert body["monitorApiKey"] == "mon-key"
        assert body["monitorUrl"] == "/api/monitoring"
        assert set(body["frp"]) == {"config", "pkiBundle"}
        assert body["frp"]["config"] and body["frp"]["pkiBundle"] == ""


class TestNotificationShape:
    def test_feed_rows_equal_to_dict(self, test_client, db_session, admin_user):
        full = Notification(
            user_id=admin_user.id,
            severity="critical",
            category="monitoring",
            event_type="monitoring.check.transition",
            title="full",
            body="CPU critical",
            source_type="server",
            source_id="srv-1",
            read_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        )
        sparse = Notification(
            user_id=admin_user.id,
            severity="info",
            category="lifecycle",
            event_type="probe",
            title="sparse",
        )
        db_session.add_all([full, sparse])
        db_session.commit()
        res = test_client.get("/api/notifications", headers=_login(test_client))
        assert res.status_code == 200, res.text
        rows = {n["id"]: n for n in res.json()}
        assert len(rows) == 2
        for row in (full, sparse):
            db_session.refresh(row)
            assert rows[row.id] == jsonable_encoder(row.to_dict())
        assert rows[sparse.id]["body"] is None and rows[sparse.id]["readAt"] is None
        assert rows[full.id]["read"] is True

    def test_prefs_equal_to_dict(self, test_client, db_session, admin_user):
        h = _login(test_client)
        put = test_client.put(
            "/api/users/me/notification-prefs",
            headers=h,
            json={
                "email": "admin@example.com",
                "telegram_chat_id": "12345",
                "subscriptions": [
                    {"scope_type": "tag", "scope_ref": "prod", "categories": ["pki"]},
                    {"scope_type": "all"},
                ],
            },
        )
        assert put.status_code == 200, put.text
        got = test_client.get("/api/users/me/notification-prefs", headers=h)
        assert got.status_code == 200, got.text
        assert got.json() == put.json()
        subs = (
            db_session.query(NotificationSubscription).order_by(NotificationSubscription.id).all()
        )
        assert got.json() == {
            "email": "admin@example.com",
            "telegramChatId": "12345",
            "subscriptions": [jsonable_encoder(s.to_dict()) for s in subs],
        }
        tagged, every = got.json()["subscriptions"]
        assert tagged["categories"] == '["pki"]'
        assert every["scopeRef"] is None and every["categories"] is None
