# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FRP input hardening (audit): boundary validation against TOML injection in the
generated frps/frpc/visitor configs, a secret entropy floor, and a fail-closed
allow-list default."""

import pytest
from pydantic import ValidationError

from app.modules.frp._helpers import get_allow_users
from app.modules.frp.schemas import FrpServerConfigCreate, FrpTunnelCreate


def _tunnel(**over):
    base = dict(
        server_id="s", frp_config_id="c", name="ok-name",
        tunnel_type="stcp", protocol="ssh", local_port=22,
    )
    base.update(over)
    return FrpTunnelCreate(**base)


def test_tunnel_name_rejects_toml_breakers():
    with pytest.raises(ValidationError):
        _tunnel(name='evil"\nauth.token = "attacker')


def test_custom_domains_rejects_newline():
    with pytest.raises(ValidationError):
        _tunnel(custom_domains="ok.example\nvhostHTTPSPort = 1")


def test_secret_key_entropy_floor():
    with pytest.raises(ValidationError):
        _tunnel(secret_key="short")  # < 16 chars
    # a sufficiently long, clean key is accepted
    assert _tunnel(secret_key="x" * 20).secret_key == "x" * 20
    # empty stays valid (server auto-generates)
    assert _tunnel(secret_key="").secret_key == ""


def test_server_extra_config_rejects_breakers():
    with pytest.raises(ValidationError):
        FrpServerConfigCreate(name="n", server_addr="a.example", extra_config={"k": 'v"\ninjected = 1'})


def test_get_allow_users_fails_closed_to_empty(db_session):
    # No assigned users and no admins -> empty allow-list (deny), NOT ["*"].
    assert get_allow_users(db_session, "no-such-server") == []
