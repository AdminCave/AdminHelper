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
