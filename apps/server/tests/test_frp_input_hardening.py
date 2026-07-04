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
from app.modules.servers.schemas import ServerCreate, ServerUpdate


def _tunnel(**over):
    base = dict(
        server_id="s",
        frp_config_id="c",
        name="ok-name",
        tunnel_type="stcp",
        protocol="ssh",
        local_port=22,
    )
    base.update(over)
    return FrpTunnelCreate(**base)


def test_tunnel_type_rejects_unknown_value():
    # 2.46: tunnel_type is a Literal, so an unknown value is rejected at the schema
    # boundary (Pydantic -> 422), not by an ad-hoc router check (-> 400).
    with pytest.raises(ValidationError):
        _tunnel(tunnel_type="ftp")
    assert _tunnel(tunnel_type="stcp").tunnel_type == "stcp"
    assert _tunnel(tunnel_type="https").tunnel_type == "https"


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
        FrpServerConfigCreate(
            name="n", server_addr="a.example", extra_config={"k": 'v"\ninjected = 1'}
        )


def test_extra_config_rejects_injection_inside_list_values():
    # A list value is not a str, so its inner strings used to bypass the
    # breaker check while the generator emitted them as raw Python repr.
    with pytest.raises(ValidationError):
        _tunnel(extra_config={"k": ['a\nauth.token = "x"']})


def test_extra_config_rejects_non_scalar_values():
    with pytest.raises(ValidationError):
        _tunnel(extra_config={"k": {"nested": 1}})
    with pytest.raises(ValidationError):
        _tunnel(extra_config={"k": [1, 2]})
    with pytest.raises(ValidationError):
        _tunnel(extra_config={"k": None})


def test_extra_config_rejects_non_bare_keys():
    # Keys are emitted unquoted; anything beyond a TOML bare key breaks or
    # extends the generated config.
    with pytest.raises(ValidationError):
        _tunnel(extra_config={"k = 1 #": "v"})
    with pytest.raises(ValidationError):
        _tunnel(extra_config={'k"': "v"})


def test_extra_config_accepts_clean_scalars():
    t = _tunnel(
        extra_config={"transport.useEncryption": True, "retries": 3, "bandwidthLimit": "1MB"}
    )
    assert t.extra_config == {
        "transport.useEncryption": True,
        "retries": 3,
        "bandwidthLimit": "1MB",
    }


def test_server_name_rejects_toml_breakers():
    # The server name flows into frpc `user`, visitor `serverUser` and the
    # bulk-ZIP path — same boundary as the FRP fields (audit residual).
    with pytest.raises(ValidationError):
        ServerCreate(name='srv"\nauth.token = "attacker', hostname="h")
    with pytest.raises(ValidationError):
        ServerUpdate(name="srv\\evil")


def test_server_name_rejects_path_traversal():
    with pytest.raises(ValidationError):
        ServerCreate(name="../escape", hostname="h")
    with pytest.raises(ValidationError):
        ServerCreate(name="..", hostname="h")
    with pytest.raises(ValidationError):
        ServerCreate(name="a/b", hostname="h")


def test_server_name_accepts_normal_names():
    assert ServerCreate(name="k01-lnx1", hostname="h").name == "k01-lnx1"
    # human-friendly names (spaces, umlauts) stay allowed — only TOML
    # breakers and path characters are the boundary
    assert ServerCreate(name="Mail Server München", hostname="h").name == "Mail Server München"
    assert ServerUpdate(name="  trimmed  ").name == "trimmed"


def test_get_allow_users_fails_closed_to_empty(db_session):
    # No assigned users and no admins -> empty allow-list (deny), NOT ["*"].
    assert get_allow_users(db_session, "no-such-server") == []
