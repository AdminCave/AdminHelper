# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the authorization filter in the FRP visitor bundle / TOML.

Background: before this test the logic `if server_ids: filter(...)` was such
that a non-admin user WITHOUT a server assignment got *all* tunnels including
secret_key (instead of none). A classic privilege-escalation trap.
"""

import logging

import pytest
from fastapi import HTTPException

from app.modules.frp.generate_router import gen_visitor_bundle, gen_visitor_toml
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.servers.models import Server


def _make_config(db, **overrides):
    cfg = FrpServerConfig(
        id="cfg-1",
        name="Default",
        server_addr="frps.example.net",
        bind_port=7000,
        auth_token="secret-frps-auth",
        **overrides,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def _make_server(db, *, sid: str, name: str):
    srv = Server(id=sid, name=name, hostname=f"{name}.example.test")
    db.add(srv)
    db.commit()
    db.refresh(srv)
    return srv


def _make_tunnel(
    db, *, tid: str, server_id: str, config_id: str, name: str, visitor_port: int = 6000
):
    tunnel = FrpTunnel(
        id=tid,
        server_id=server_id,
        frp_config_id=config_id,
        name=name,
        tunnel_type="stcp",
        protocol="ssh",
        local_port=22,
        secret_key="super-secret-do-not-leak",
        visitor_port=visitor_port,
        enabled=True,
    )
    db.add(tunnel)
    db.commit()
    db.refresh(tunnel)
    return tunnel


@pytest.fixture()
def two_servers_with_tunnels(db_session):
    cfg = _make_config(db_session)
    _make_server(db_session, sid="srv-a", name="serverA")
    _make_server(db_session, sid="srv-b", name="serverB")
    _make_tunnel(
        db_session, tid="t-a", server_id="srv-a", config_id=cfg.id, name="a-ssh", visitor_port=6000
    )
    _make_tunnel(
        db_session, tid="t-b", server_id="srv-b", config_id=cfg.id, name="b-ssh", visitor_port=6001
    )
    return cfg


class TestVisitorBundlePermissions:
    """Regression: a non-admin without assignments must see NO tunnels."""

    def test_non_admin_without_assignments_is_refused(
        self, db_session, normal_user, two_servers_with_tunnels
    ):
        # 3.33: no visible STCP tunnels -> refuse, so the shared frps auth token is
        # never handed to an unassigned user (the bundle used to embed it regardless).
        with pytest.raises(HTTPException) as exc:
            gen_visitor_bundle(config_id=None, db=db_session, current_user=normal_user)
        assert exc.value.status_code == 404

    def test_non_admin_with_one_assignment_sees_only_assigned_tunnel(
        self, db_session, normal_user, two_servers_with_tunnels
    ):
        srv_a = db_session.query(Server).filter(Server.id == "srv-a").first()
        normal_user.servers.append(srv_a)
        db_session.commit()

        result = gen_visitor_bundle(config_id=None, db=db_session, current_user=normal_user)
        assert "a-ssh" in result["toml"]
        assert "b-ssh" not in result["toml"], "User sollte Tunnel B nicht sehen"

    def test_admin_sees_all_tunnels(self, db_session, admin_user, two_servers_with_tunnels):
        result = gen_visitor_bundle(config_id=None, db=db_session, current_user=admin_user)
        assert "a-ssh" in result["toml"]
        assert "b-ssh" in result["toml"]

    def test_visitor_tunnels_eager_load_target_server(
        self, db_session, admin_user, two_servers_with_tunnels
    ):
        # 5.29: _visible_stcp_tunnels eager-loads target_server (joinedload) so generate_visitor_toml,
        # which reads tunnel.target_server.name per tunnel, doesn't fire a lazy SELECT per tunnel.
        from sqlalchemy import inspect

        from app.modules.frp.generate_router import _visible_stcp_tunnels

        cfg = db_session.query(FrpServerConfig).first()
        tunnels = _visible_stcp_tunnels(db_session, cfg, admin_user)
        assert tunnels, "fixture should yield stcp tunnels"
        for t in tunnels:
            # target_server already loaded (not lazy) → the joinedload did it; without the fix it
            # would be in the unloaded set and read as a per-tunnel SELECT later.
            assert "target_server" not in inspect(t).unloaded, "target_server is lazy-loaded (N+1)"


class TestVisitorTomlPermissions:
    """Same auth filter in the /generate/visitor-toml endpoint."""

    def test_non_admin_without_assignments_is_refused(
        self, db_session, normal_user, two_servers_with_tunnels
    ):
        # 3.33: same refusal in the TOML endpoint — no visible tunnels, no token.
        with pytest.raises(HTTPException) as exc:
            gen_visitor_toml(config_id=None, user_id=None, db=db_session, current_user=normal_user)
        assert exc.value.status_code == 404

    def test_admin_sees_all_in_visitor_toml(self, db_session, admin_user, two_servers_with_tunnels):
        response = gen_visitor_toml(
            config_id=None, user_id=None, db=db_session, current_user=admin_user
        )
        body = response.body.decode("utf-8")
        assert "a-ssh" in body
        assert "b-ssh" in body


def test_attach_auto_connection_links_stcp_and_passes_tags(db_session):
    """2.47: the shared _attach_auto_connection helper (create_tunnel + update_tunnel)
    creates the paired connection for an stcp tunnel, links it back, and passes the
    tunnel's JSON-encoded tags through unchanged (the subtle create/update tag
    difference the refactor unified)."""
    from app.modules.connections.models import Connection
    from app.modules.frp.tunnel_router import _attach_auto_connection

    cfg = _make_config(db_session)
    srv = _make_server(db_session, sid="srv-auto", name="autohost")

    tunnel = FrpTunnel(
        id="t-auto",
        server_id=srv.id,
        frp_config_id=cfg.id,
        name="db",
        tunnel_type="stcp",
        protocol="ssh",
        local_port=22,
        visitor_port=6100,
        tags='["prod"]',
    )
    db_session.add(tunnel)
    db_session.flush()

    _attach_auto_connection(db_session, tunnel, "opsuser")

    conn = db_session.query(Connection).filter(Connection.id == tunnel.connection_id).one()
    assert conn.kind == "ssh"
    assert conn.port == 6100
    assert conn.tags == '["prod"]'  # tunnel.tags passed through, not re-encoded
    assert conn.username == "opsuser"


def _login(client, username="admin", password="adminpass"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_frpc_toml_endpoint_wires_allow_users(
    test_client, db_session, admin_user, two_servers_with_tunnels
):
    # 6.73: gen_frpc_toml wires get_allow_users -> allowUsers in the TOML. The admin is auto-authorized,
    # so the list is ["admin"], NOT the fail-closed ['ops-admin'] fallback — a broken hand-off there
    # would silently strip legitimate users' tunnel access.
    h = _login(test_client)
    r = test_client.get("/api/frp/generate/frpc-toml/srv-a", headers=h)
    assert r.status_code == 200, r.text
    assert "allowUsers" in r.text
    assert '"admin"' in r.text, r.text
    assert "ops-admin" not in r.text


def test_get_allow_users_is_sorted_and_unique(db_session, admin_user):
    # R-0435: allowUsers and the agent's config-hash are built from this list. A set of strings
    # iterates in the order of the per-process hash seed, so an unsorted list changed both after
    # every server restart (and per worker) without any change in the data. Twelve names make a
    # sorted order by chance practically impossible (1 in 12!).
    from app.modules.frp._helpers import get_allow_users
    from app.modules.users.models import User

    srv = _make_server(db_session, sid="srv-order", name="orderhost")
    # (name, is_admin, assigned to srv); the assigned admins come back from both queries.
    for name, is_admin, assigned in (
        ("zoe", True, True),
        ("yusuf", False, True),
        ("mallory", True, True),
        ("bob", False, True),
        ("xena", False, True),
        ("victor", True, False),
        ("carol", False, True),
        ("wendy", False, True),
        ("dave", False, True),
        ("frank", False, True),
        ("erin", False, True),
    ):
        user = User(username=name, hashed_password="unused", is_admin=is_admin)
        if assigned:
            user.servers.append(srv)
        db_session.add(user)
    db_session.commit()

    first = get_allow_users(db_session, srv.id)
    assert first == [
        "admin",
        "bob",
        "carol",
        "dave",
        "erin",
        "frank",
        "mallory",
        "victor",
        "wendy",
        "xena",
        "yusuf",
        "zoe",
    ]
    assert get_allow_users(db_session, srv.id) == first


def test_bulk_zip_contains_per_server_configs(
    test_client, db_session, admin_user, two_servers_with_tunnels
):
    # 6.73: the bulk-zip path writes frps.toml plus one clients/<server>/frpc.toml per server.
    import io
    import zipfile

    h = _login(test_client)
    r = test_client.get("/api/frp/generate/bulk-zip", headers=h)
    assert r.status_code == 200, r.text
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "frps.toml" in names
    assert "clients/serverA/frpc.toml" in names, names
    assert "clients/serverB/frpc.toml" in names, names


def test_visitor_toml_admin_for_unknown_user_returns_404(
    test_client, db_session, admin_user, two_servers_with_tunnels
):
    # 6.73: an admin generating a visitor TOML for another user via ?user_id — an unknown user_id must
    # 404 with the user error (not fall through to the tunnel check).
    h = _login(test_client)
    r = test_client.get("/api/frp/generate/visitor-toml?user_id=999999", headers=h)
    assert r.status_code == 404, r.text
    assert "Benutzer" in r.json()["detail"]


class TestTunnelsWithoutSecret:
    """A stcp tunnel without a secret is left out of every generated config. A user or server
    whose only stcp tunnel lacks one is answered like one without tunnels: the shared frps
    auth token goes out only next to a tunnel that can be used."""

    @staticmethod
    def _without_secret(db, tid: str) -> None:
        db.get(FrpTunnel, tid).secret_key = None
        db.commit()

    @staticmethod
    def _assign(db, user, *server_ids: str) -> None:
        for sid in server_ids:
            user.servers.append(db.get(Server, sid))
        db.commit()

    def test_visitor_bundle_refuses(self, db_session, normal_user, two_servers_with_tunnels):
        self._without_secret(db_session, "t-a")
        self._assign(db_session, normal_user, "srv-a")
        with pytest.raises(HTTPException) as exc:
            gen_visitor_bundle(config_id=None, db=db_session, current_user=normal_user)
        assert exc.value.status_code == 404

    def test_visitor_toml_refuses(self, db_session, normal_user, two_servers_with_tunnels):
        self._without_secret(db_session, "t-a")
        self._assign(db_session, normal_user, "srv-a")
        with pytest.raises(HTTPException) as exc:
            gen_visitor_toml(config_id=None, user_id=None, db=db_session, current_user=normal_user)
        assert exc.value.status_code == 404

    def test_frpc_toml_refuses(self, test_client, db_session, admin_user, two_servers_with_tunnels):
        self._without_secret(db_session, "t-a")
        r = test_client.get("/api/frp/generate/frpc-toml/srv-a", headers=_login(test_client))
        assert r.status_code == 404, r.text

    def test_bulk_zip_writes_no_visitor_without_one(
        self, test_client, db_session, admin_user, normal_user, two_servers_with_tunnels
    ):
        import io
        import zipfile

        self._without_secret(db_session, "t-a")
        self._assign(db_session, normal_user, "srv-a")
        r = test_client.get("/api/frp/generate/bulk-zip", headers=_login(test_client))
        assert r.status_code == 200, r.text
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        assert f"visitors/{normal_user.username}.toml" not in names, names
        assert "clients/serverB/frpc.toml" in names, names

    @staticmethod
    def _zip_names(test_client) -> list[str]:
        import io
        import zipfile

        r = test_client.get("/api/frp/generate/bulk-zip", headers=_login(test_client))
        assert r.status_code == 200, r.text
        return zipfile.ZipFile(io.BytesIO(r.content)).namelist()

    def test_bulk_zip_leaves_out_a_server_without_usable_tunnel(
        self, test_client, db_session, admin_user, two_servers_with_tunnels
    ):
        # R-0148: the single route answers 404 for such a server; the ZIP follows the
        # same rule instead of shipping an frpc.toml with auth.token and no proxy.
        self._without_secret(db_session, "t-a")
        names = self._zip_names(test_client)
        assert "clients/serverA/frpc.toml" not in names, names
        assert "clients/serverB/frpc.toml" in names, names

    def test_bulk_zip_without_any_usable_tunnel_is_frps_only(
        self, test_client, db_session, admin_user, two_servers_with_tunnels
    ):
        # No user has servers assigned, so the shared visitor.toml path runs.
        self._without_secret(db_session, "t-a")
        self._without_secret(db_session, "t-b")
        assert self._zip_names(test_client) == ["frps.toml"]

    def test_bulk_zip_keeps_the_usable_tunnel_next_to_a_secretless_one(
        self, test_client, db_session, admin_user, two_servers_with_tunnels
    ):
        import io
        import zipfile

        _make_tunnel(
            db_session,
            tid="t-a2",
            server_id="srv-a",
            config_id=two_servers_with_tunnels.id,
            name="a2-ssh",
            visitor_port=6002,
        )
        self._without_secret(db_session, "t-a")
        r = test_client.get("/api/frp/generate/bulk-zip", headers=_login(test_client))
        assert r.status_code == 200, r.text
        frpc = zipfile.ZipFile(io.BytesIO(r.content)).read("clients/serverA/frpc.toml").decode()
        assert frpc.count("[[proxies]]") == 1, frpc
        assert '"a2-ssh"' in frpc and '"a-ssh"' not in frpc, frpc

    def test_bulk_zip_warns_once_per_secretless_tunnel(
        self, test_client, db_session, admin_user, normal_user, two_servers_with_tunnels, caplog
    ):
        # Filtered once at the top: one warning per tunnel, not one per server, user and
        # generator call.
        self._without_secret(db_session, "t-a")
        self._assign(db_session, normal_user, "srv-a", "srv-b")
        with caplog.at_level(logging.WARNING, logger="app.modules.frp.config_generator"):
            self._zip_names(test_client)
        hits = [
            r
            for r in caplog.records
            if "a-ssh" in r.getMessage() and "without a secret" in r.getMessage()
        ]
        assert len(hits) == 1, [r.getMessage() for r in hits]

    def test_one_usable_tunnel_is_enough(self, db_session, normal_user, two_servers_with_tunnels):
        self._without_secret(db_session, "t-a")
        self._assign(db_session, normal_user, "srv-a", "srv-b")
        toml = gen_visitor_bundle(config_id=None, db=db_session, current_user=normal_user)["toml"]
        assert toml.count("[[visitors]]") == 1
        assert "b-ssh" in toml and "a-ssh" not in toml


class TestTunnelsWithoutVisitorPort:
    """R-0533: a stcp tunnel whose stored visitor_port is no port from 1 to 65535 (rows from
    before the schema bounded it, NULL from migration f1a2b3c4d5e6) is left out of every visitor
    config, and a user whose visible stcp tunnels all have one is answered like one without
    tunnels. The agent's frpc config keeps the tunnel's proxy."""

    _assign = staticmethod(TestTunnelsWithoutSecret._assign)
    _zip_names = staticmethod(TestTunnelsWithoutSecret._zip_names)

    @staticmethod
    def _set_port(db, tid: str, port: int | None) -> None:
        db.get(FrpTunnel, tid).visitor_port = port
        db.commit()

    @pytest.mark.parametrize("port", [None, 0, 70000])
    def test_visitor_bundle_refuses(self, db_session, normal_user, two_servers_with_tunnels, port):
        self._set_port(db_session, "t-a", port)
        self._assign(db_session, normal_user, "srv-a")
        with pytest.raises(HTTPException) as exc:
            gen_visitor_bundle(config_id=None, db=db_session, current_user=normal_user)
        assert exc.value.status_code == 404

    @pytest.mark.parametrize("port", [None, 0, 70000])
    def test_visitor_toml_refuses(self, db_session, normal_user, two_servers_with_tunnels, port):
        self._set_port(db_session, "t-a", port)
        self._assign(db_session, normal_user, "srv-a")
        with pytest.raises(HTTPException) as exc:
            gen_visitor_toml(config_id=None, user_id=None, db=db_session, current_user=normal_user)
        assert exc.value.status_code == 404

    def test_one_usable_tunnel_is_enough(self, db_session, admin_user, two_servers_with_tunnels):
        self._set_port(db_session, "t-a", 70000)
        response = gen_visitor_toml(
            config_id=None, user_id=None, db=db_session, current_user=admin_user
        )
        body = response.body.decode("utf-8")
        assert body.count("[[visitors]]") == 1
        assert "b-ssh" in body and "a-ssh" not in body

    def test_bulk_zip_writes_no_visitor_without_one(
        self, test_client, db_session, admin_user, normal_user, two_servers_with_tunnels
    ):
        import io
        import zipfile

        self._set_port(db_session, "t-a", 70000)
        self._assign(db_session, normal_user, "srv-a")
        r = test_client.get("/api/frp/generate/bulk-zip", headers=_login(test_client))
        assert r.status_code == 200, r.text
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        assert f"visitors/{normal_user.username}.toml" not in zf.namelist(), zf.namelist()
        # The agent side is unchanged: serverA keeps the tunnel's proxy.
        frpc = zf.read("clients/serverA/frpc.toml").decode()
        assert '"a-ssh"' in frpc, frpc

    def test_bulk_zip_shared_visitor_keeps_the_usable_tunnel(
        self, test_client, db_session, admin_user, two_servers_with_tunnels
    ):
        import io
        import zipfile

        # No user has servers assigned, so the shared visitor.toml path runs.
        self._set_port(db_session, "t-a", None)
        r = test_client.get("/api/frp/generate/bulk-zip", headers=_login(test_client))
        assert r.status_code == 200, r.text
        visitor = zipfile.ZipFile(io.BytesIO(r.content)).read("visitor.toml").decode()
        assert visitor.count("[[visitors]]") == 1, visitor
        assert "b-ssh" in visitor and "a-ssh" not in visitor, visitor

    def test_bulk_zip_without_any_usable_visitor_writes_none(
        self, test_client, db_session, admin_user, two_servers_with_tunnels
    ):
        self._set_port(db_session, "t-a", 0)
        self._set_port(db_session, "t-b", 70000)
        names = self._zip_names(test_client)
        assert "visitor.toml" not in names, names
        assert "clients/serverA/frpc.toml" in names and "clients/serverB/frpc.toml" in names, names

    def test_bulk_zip_warns_once_per_tunnel(
        self, test_client, db_session, admin_user, normal_user, two_servers_with_tunnels, caplog
    ):
        # Filtered once for all users: one warning per tunnel, not one per user.
        self._set_port(db_session, "t-a", 70000)
        self._assign(db_session, normal_user, "srv-a", "srv-b")
        self._assign(db_session, admin_user, "srv-a", "srv-b")
        with caplog.at_level(logging.WARNING, logger="app.modules.frp.config_generator"):
            self._zip_names(test_client)
        hits = [
            r
            for r in caplog.records
            if "a-ssh" in r.getMessage() and "visitor_port" in r.getMessage()
        ]
        assert len(hits) == 1, [r.getMessage() for r in hits]


class TestNamesTheApiRefuses:
    """A server or user name stored before the schema check (an import, an old row) is
    written verbatim into TOML strings by the generators. Such a name is left out, and a
    route that would have nothing else to hand out answers like one without tunnels."""

    REFUSED = 'evil"name'

    @staticmethod
    def _rename_server(db, sid: str, name: str) -> None:
        db.get(Server, sid).name = name
        db.commit()

    def test_frpc_toml_for_a_refused_server_name_is_404(
        self, test_client, db_session, admin_user, two_servers_with_tunnels
    ):
        self._rename_server(db_session, "srv-a", self.REFUSED)
        r = test_client.get("/api/frp/generate/frpc-toml/srv-a", headers=_login(test_client))
        assert r.status_code == 404, r.text
        assert "super-secret" not in r.text and "secret-frps-auth" not in r.text

    def test_visitor_routes_leave_out_a_tunnel_of_a_refused_server_name(
        self, db_session, admin_user, two_servers_with_tunnels
    ):
        self._rename_server(db_session, "srv-a", self.REFUSED)
        bundle = gen_visitor_bundle(config_id=None, db=db_session, current_user=admin_user)
        assert "a-ssh" not in bundle["toml"] and self.REFUSED not in bundle["toml"]
        assert "b-ssh" in bundle["toml"]
        toml = gen_visitor_toml(
            config_id=None, user_id=None, db=db_session, current_user=admin_user
        ).body.decode()
        assert "a-ssh" not in toml and "b-ssh" in toml

    def test_visitor_routes_refuse_a_user_with_a_refused_name(
        self, db_session, normal_user, two_servers_with_tunnels
    ):
        normal_user.servers.append(db_session.get(Server, "srv-a"))
        normal_user.username = self.REFUSED
        db_session.commit()
        with pytest.raises(HTTPException) as exc:
            gen_visitor_bundle(config_id=None, db=db_session, current_user=normal_user)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            gen_visitor_toml(config_id=None, user_id=None, db=db_session, current_user=normal_user)
        assert exc.value.status_code == 404

    def test_bulk_zip_skips_refused_server_and_user_names(
        self, test_client, db_session, admin_user, normal_user, two_servers_with_tunnels
    ):
        import io
        import tomllib
        import zipfile

        normal_user.servers.append(db_session.get(Server, "srv-b"))
        normal_user.username = 'eve"'
        db_session.commit()
        self._rename_server(db_session, "srv-a", self.REFUSED)
        h = _login(test_client)
        r = test_client.get("/api/frp/generate/bulk-zip", headers=h)
        assert r.status_code == 200, r.text
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        assert "clients/serverB/frpc.toml" in names, names
        assert not any(self.REFUSED in n or "eve" in n for n in names), names
        # The only user with servers is left out: no shared visitor.toml in its place.
        assert "visitor.toml" not in names, names
        for n in names:
            tomllib.loads(zf.read(n).decode())  # every file still parses
        assert all(self.REFUSED not in zf.read(n).decode() for n in names)


class TestFilterWarnsOncePerTunnel:
    """The sync and the hash poll run the filters every few seconds; a row that stays
    left out warns once, not on every poll (R-0969), and its name is quoted with %r, so
    a stored name with a line break cannot fake a log line (R-0971)."""

    @staticmethod
    def _tunnel(**overrides) -> FrpTunnel:
        fields = {
            "name": "x-ssh",
            "tunnel_type": "stcp",
            "local_ip": "127.0.0.1",
            "local_port": 22,
            "secret_key": "s" * 16,
            "visitor_port": 6000,
            "enabled": True,
        }
        fields.update(overrides)
        return FrpTunnel(**fields)

    @pytest.mark.parametrize(
        ("filter_name", "overrides"),
        [
            ("without_secretless_stcp", {"secret_key": None}),
            ("without_unbindable_visitor", {"visitor_port": 70000}),
            ("without_refused_fields", {"local_ip": "127.0.0.1\nx"}),
            ("without_unreachable_local", {"local_port": 0}),
        ],
    )
    def test_second_call_does_not_warn_again(self, caplog, filter_name, overrides):
        from app.modules.frp import config_generator

        run = getattr(config_generator, filter_name)
        tunnel = self._tunnel(name="x-ssh\nforged", **overrides)
        with caplog.at_level(logging.WARNING, logger="app.modules.frp.config_generator"):
            assert run([tunnel]) == []
            assert run([tunnel]) == []
        messages = [r.getMessage() for r in caplog.records]
        assert len(messages) == 1, messages
        assert "'x-ssh\\nforged'" in messages[0] and "\n" not in messages[0], messages

    def test_each_reason_warns_once(self, caplog):
        from app.modules.frp import config_generator

        tunnel = self._tunnel(secret_key=None, local_port=0)
        with caplog.at_level(logging.WARNING, logger="app.modules.frp.config_generator"):
            for _ in range(2):
                config_generator.without_secretless_stcp([tunnel])
                config_generator.without_unreachable_local([tunnel])
        assert len(caplog.records) == 2, [r.getMessage() for r in caplog.records]
