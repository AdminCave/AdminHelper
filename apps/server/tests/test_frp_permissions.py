# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the authorization filter in the FRP visitor bundle / TOML.

Background: before this test the logic `if server_ids: filter(...)` was such
that a non-admin user WITHOUT a server assignment got *all* tunnels including
secret_key (instead of none). A classic privilege-escalation trap.
"""

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
