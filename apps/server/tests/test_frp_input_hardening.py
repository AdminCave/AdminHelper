# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FRP input hardening (audit): boundary validation against TOML injection in the
generated frps/frpc/visitor configs, a secret entropy floor, and a fail-closed
allow-list default."""

import io
import json
import logging
import time
import tomllib
import zipfile

import pytest
from pydantic import ValidationError

from app.modules.frp._helpers import get_allow_users
from app.modules.frp.config_generator import (
    active_tunnels,
    generate_frpc_toml,
    generate_frps_toml,
    generate_visitor_toml,
)
from app.modules.frp.extra_config import ALLOWED_KEYS
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.schemas import (
    _GENERATOR_PROXY_KEYS,
    FrpServerConfigCreate,
    FrpServerConfigUpdate,
    FrpTunnelCreate,
    FrpTunnelUpdate,
    is_plugin_key,
)
from app.modules.servers.models import Server
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


def test_tunnel_name_rejects_del():
    # U+007F is a control character to TOML as well; a basic string may not carry it.
    with pytest.raises(ValidationError):
        _tunnel(name="ok\x7fname")
    with pytest.raises(ValidationError):
        FrpTunnelUpdate(name="ok\x7fname")


@pytest.mark.parametrize("value", ["ok\ud800name", "\udfff", "\udc80" + "x" * 20], ids=repr)
def test_toml_strings_reject_a_lone_surrogate(value):
    # A lone surrogate has no UTF-8 form, so no generated config can carry it.
    with pytest.raises(ValidationError, match="surrogate"):
        _tunnel(name=value)
    with pytest.raises(ValidationError, match="surrogate"):
        FrpTunnelUpdate(custom_domains=value)
    with pytest.raises(ValidationError, match="surrogate"):
        _tunnel(secret_key=value + "x" * 16)
    with pytest.raises(ValidationError, match="surrogate"):
        FrpServerConfigCreate(name="n", server_addr=value)
    with pytest.raises(ValidationError, match="surrogate"):
        ServerCreate(name=value, hostname="h")


def test_toml_strings_take_the_neighbours_of_the_surrogates():
    for value in ("ok\ud7ffname", "ok\ue000name"):
        assert _tunnel(name=value).name == value
        assert ServerCreate(name=value, hostname="h").name == value


# R-0786: TOML allows U+0080 to U+009F in a basic string, but the agent refuses every line
# of a frpc.toml with a unicode.IsControl character, so the host would get no config at all.
@pytest.mark.parametrize("char", ["\x80", "\x85", "\x9f"], ids=repr)
def test_toml_strings_reject_a_c1_control_character(char):
    value = f"ok{char}name"
    for field in ("name", "local_ip", "custom_domains"):
        with pytest.raises(ValidationError, match="unzul\u00e4ssige Zeichen"):
            _tunnel(**{field: value})
    with pytest.raises(ValidationError, match="unzul\u00e4ssige Zeichen"):
        _tunnel(secret_key=value + "x" * 16)
    with pytest.raises(ValidationError, match="unzul\u00e4ssige Zeichen"):
        _tunnel(extra_config={"k": value})
    with pytest.raises(ValidationError, match="unzul\u00e4ssige Zeichen"):
        FrpTunnelUpdate(name=value)
    with pytest.raises(ValidationError, match="unzul\u00e4ssige Zeichen"):
        FrpServerConfigCreate(name="n", server_addr=value)
    with pytest.raises(ValidationError, match="unzul\u00e4ssige Zeichen"):
        FrpServerConfigCreate(name="n", server_addr="a.example", auth_token=value + "x" * 16)
    with pytest.raises(ValidationError, match="unzul\u00e4ssige Zeichen"):
        ServerCreate(name=value, hostname="h")
    with pytest.raises(ValidationError, match="unzul\u00e4ssige Zeichen"):
        ServerUpdate(name=value)


@pytest.mark.parametrize("char", ["\x7e", "\xa0"], ids=repr)
def test_toml_strings_take_the_neighbours_of_the_c1_control_characters(char):
    value = f"ok{char}name"
    for field in ("name", "local_ip", "custom_domains"):
        assert getattr(_tunnel(**{field: value}), field) == value
    assert _tunnel(secret_key=value + "x" * 16).secret_key == value + "x" * 16
    assert _tunnel(extra_config={"k": value}).extra_config == {"k": value}
    assert FrpTunnelUpdate(name=value).name == value
    assert FrpServerConfigCreate(name="n", server_addr=value).server_addr == value
    token = value + "x" * 16
    config = FrpServerConfigCreate(name="n", server_addr="a.example", auth_token=token)
    assert config.auth_token == token
    assert ServerCreate(name=value, hostname="h").name == value
    assert ServerUpdate(name=value).name == value


# frp renders a config file as a Go template before it reads the TOML, so `{{` in a
# value the generator writes verbatim would open a template action.
@pytest.mark.parametrize("value", ["{{", "a{{b", "{{ x }}", "{{{"], ids=repr)
def test_toml_strings_reject_a_template_opener(value):
    with pytest.raises(ValidationError, match="template"):
        _tunnel(name=value)
    with pytest.raises(ValidationError, match="template"):
        FrpTunnelUpdate(name=value)
    with pytest.raises(ValidationError, match="template"):
        FrpTunnelUpdate(custom_domains=value)
    with pytest.raises(ValidationError, match="template"):
        _tunnel(secret_key=value + "x" * 16)
    with pytest.raises(ValidationError, match="template"):
        _tunnel(extra_config={"k": value})
    with pytest.raises(ValidationError, match="template"):
        FrpServerConfigCreate(name="n", server_addr=value)
    with pytest.raises(ValidationError, match="template"):
        FrpServerConfigUpdate(server_addr=value)
    with pytest.raises(ValidationError, match="template"):
        FrpServerConfigCreate(name="n", server_addr="a.example", extra_config={"log.level": value})
    with pytest.raises(ValidationError, match="template"):
        ServerCreate(name=value, hostname="h")
    with pytest.raises(ValidationError, match="template"):
        ServerUpdate(name=value)


@pytest.mark.parametrize("value", ["{", "a{b", "{ {", "}}", "a}}b", "}}{"], ids=repr)
def test_toml_strings_take_a_single_brace_and_a_closing_pair(value):
    assert _tunnel(name=value).name == value
    assert _tunnel(secret_key=value + "x" * 16).secret_key == value + "x" * 16
    assert FrpServerConfigCreate(name="n", server_addr=value).server_addr == value
    assert ServerCreate(name=value, hostname="h").name == value


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


def test_dashboard_password_requires_entropy_floor():
    # 3.35: dashboard_password guards the frps web UI (all proxy metadata + traffic),
    # so it gets the same >=16-char floor as auth_token, not just the injection guard.
    with pytest.raises(ValidationError):
        FrpServerConfigCreate(name="n", server_addr="a.example", dashboard_password="short")
    ok = FrpServerConfigCreate(name="n", server_addr="a.example", dashboard_password="x" * 20)
    assert ok.dashboard_password == "x" * 20
    # empty stays valid — the router auto-generates when a dashboard port is set
    empty = FrpServerConfigCreate(name="n", server_addr="a.example", dashboard_password="")
    assert empty.dashboard_password == ""


def test_server_extra_config_rejects_breakers():
    with pytest.raises(ValidationError):
        FrpServerConfigCreate(
            name="n", server_addr="a.example", extra_config={"log.level": 'v"\ninjected = 1'}
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


@pytest.mark.parametrize("model", [FrpTunnelCreate, FrpTunnelUpdate])
def test_extra_config_rejects_key_with_trailing_newline(model):
    # In Python `$` also matches before a trailing "\n", so an anchored .match let
    # "abc\n" through; the generator writes it unquoted and frpc.toml no longer parses.
    build = _tunnel if model is FrpTunnelCreate else model
    with pytest.raises(ValidationError) as exc:
        build(extra_config={"abc\n": 1})
    assert "'abc\n'" in exc.value.errors()[0]["msg"]


# frp maps the fields of a proxy without regard to case and reads its plugin from `plugin`;
# the server sets up no proxy plugin, and the agent refuses a frpc.toml with such a key.
PLUGIN_KEYS = ["plugin", "plugin.type", "PLUGIN.type", "Plugin.localPath", "pLuGiN.unixPath"]
NOT_PLUGIN_KEYS = ["plugins.x", "myplugin.type", "x.plugin", "transport.useCompression"]


@pytest.mark.parametrize("key", PLUGIN_KEYS)
@pytest.mark.parametrize("model", [FrpTunnelCreate, FrpTunnelUpdate])
def test_tunnel_extra_config_rejects_a_plugin_key(model, key):
    build = _tunnel if model is FrpTunnelCreate else model
    with pytest.raises(ValidationError) as exc:
        build(extra_config={"transport.useCompression": True, key: "static_file"})
    msg = exc.value.errors()[0]["msg"]
    assert f"'{key}'" in msg and "plugin family" in msg, msg


@pytest.mark.parametrize("key", NOT_PLUGIN_KEYS)
@pytest.mark.parametrize("model", [FrpTunnelCreate, FrpTunnelUpdate])
def test_tunnel_extra_config_takes_the_neighbours_of_the_plugin_family(model, key):
    build = _tunnel if model is FrpTunnelCreate else model
    assert build(extra_config={key: True}).extra_config == {key: True}


def test_is_plugin_key_reads_only_the_first_segment():
    assert is_plugin_key("plugin")
    assert is_plugin_key("PLUGIN.x")
    for key in ("plugins", "x.plugin", "plugin_x"):
        assert not is_plugin_key(key), key


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


# app.core.bounds.IntColumn — every one of these is a Column(Integer).
INT_COLUMN_MAX = 2147483647
INT_COLUMN_MIN = -2147483648


def _config(**over):
    base = dict(name="c", server_addr="frps.example")
    base.update(over)
    return FrpServerConfigCreate(**base)


def _build(model, **over):
    """The Create models need their required fields; the Update models are
    all-optional, so the field under test is the whole payload."""
    if model is FrpServerConfigCreate:
        return _config(**over)
    if model is FrpTunnelCreate:
        return _tunnel(**over)
    return model(**over)


# The integer fields of the server config are narrower than their column since
# T23, visitor_port since R-0533; the port-range and max-ports tests below hold them.
@pytest.mark.parametrize(
    "model,field",
    [
        (FrpTunnelCreate, "local_port"),
        (FrpTunnelUpdate, "local_port"),
    ],
)
def test_integer_body_fields_hold_at_both_edges(model, field):
    """Both edges of the INTEGER column each of these lands in (T5).

    Unbounded they reached the INSERT and Postgres answered NumericValueOutOfRange,
    uncaught — HTTP 500 instead of 422. Reproduced per field 2026-09-22 against
    POST /api/frp/server-config and POST /api/frp/tunnels."""
    for edge in (INT_COLUMN_MIN, INT_COLUMN_MAX):
        assert getattr(_build(model, **{field: edge}), field) == edge

    for past in (INT_COLUMN_MIN - 1, INT_COLUMN_MAX + 1):
        with pytest.raises(ValidationError):
            _build(model, **{field: past})


# T23 (R-0411): bindPort, vhostHTTPSPort and webServer.port of the generated
# frps.toml. A value outside 1-65535 fit the INTEGER column, so it was stored and
# written into frps.toml as is.
SERVER_CONFIG_PORTS = ("bind_port", "vhost_https_port", "dashboard_port")
PORTS_OUT_OF_RANGE = (0, -1, 65536)


@pytest.mark.parametrize("field", SERVER_CONFIG_PORTS)
@pytest.mark.parametrize("model", [FrpServerConfigCreate, FrpServerConfigUpdate])
def test_server_config_ports_hold_the_port_range(model, field):
    for edge in (1, 65535):
        assert getattr(_build(model, **{field: edge}), field) == edge

    for bad in PORTS_OUT_OF_RANGE:
        with pytest.raises(ValidationError):
            _build(model, **{field: bad})


@pytest.mark.parametrize("field", SERVER_CONFIG_PORTS)
@pytest.mark.parametrize("model", [FrpServerConfigCreate, FrpServerConfigUpdate])
def test_server_config_ports_publish_the_port_range(model, field):
    """The bound is part of the contract, so it has to reach the schema — a
    constraint lost on the way through an alias validates nothing and says
    nothing. Optional ports carry it in the integer branch of their anyOf."""
    prop = model.model_json_schema()["properties"][field]
    branches = prop.get("anyOf", [prop])
    integers = [b for b in branches if b.get("type") == "integer"]
    assert len(integers) == 1, prop
    assert (integers[0]["minimum"], integers[0]["maximum"]) == (1, 65535), prop

    nullable = any(b.get("type") == "null" for b in branches)
    # bind_port is never null: the generator would write `bindPort = None`.
    # The other two are null for "off".
    assert nullable == (field != "bind_port"), prop


@pytest.mark.parametrize("model", [FrpServerConfigCreate, FrpServerConfigUpdate])
def test_max_ports_per_client_takes_no_negative_value(model):
    """frps enforces maxPortsPerClient only while it is > 0, so a negative value
    lifts the cap the generator always sets (T23). 0 and null stay the default."""
    for ok in (0, 16, INT_COLUMN_MAX, None):
        assert _build(model, max_ports_per_client=ok).max_ports_per_client == ok

    for bad in (-1, INT_COLUMN_MIN, INT_COLUMN_MAX + 1):
        with pytest.raises(ValidationError):
            _build(model, max_ports_per_client=bad)

    prop = model.model_json_schema()["properties"]["max_ports_per_client"]
    integers = [b for b in prop["anyOf"] if b.get("type") == "integer"]
    assert [(b["minimum"], b["maximum"]) for b in integers] == [(0, INT_COLUMN_MAX)], prop


def _login(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_config_via_api(client, monkeypatch, **fields):
    import app.modules.frp.config_router as cr

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    h = _login(client)
    created = client.post(
        "/api/frp/server-config",
        json={"name": "test-frps", "server_addr": "frps.example.net", **fields},
        headers=h,
    )
    assert created.status_code == 201, created.text
    return h, created.json()["id"]


def _stored(db_session, config_id):
    stored = db_session.get(FrpServerConfig, config_id)
    db_session.refresh(stored)
    return stored


@pytest.mark.parametrize("field", SERVER_CONFIG_PORTS)
def test_server_config_create_answers_422_outside_the_port_range(
    test_client, db_session, admin_user, monkeypatch, field
):
    import app.modules.frp.config_router as cr

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    h = _login(test_client)
    for bad in PORTS_OUT_OF_RANGE:
        r = test_client.post(
            "/api/frp/server-config",
            json={"name": "test-frps", "server_addr": "frps.example.net", field: bad},
            headers=h,
        )
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["detail"][0]["loc"] == ["body", field], r.text
    assert db_session.query(FrpServerConfig).count() == 0


@pytest.mark.parametrize("field", SERVER_CONFIG_PORTS)
def test_server_config_update_holds_the_port_range(
    test_client, db_session, admin_user, monkeypatch, field
):
    h, cid = _create_config_via_api(test_client, monkeypatch, **{field: 7443})
    for bad in PORTS_OUT_OF_RANGE:
        r = test_client.put(f"/api/frp/server-config/{cid}", json={field: bad}, headers=h)
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["detail"][0]["loc"] == ["body", field], r.text
        assert getattr(_stored(db_session, cid), field) == 7443

    for edge in (1, 65535):
        r = test_client.put(f"/api/frp/server-config/{cid}", json={field: edge}, headers=h)
        assert r.status_code == 200, (edge, r.text)
        assert getattr(_stored(db_session, cid), field) == edge


def test_server_config_update_rejects_a_null_bind_port(
    test_client, db_session, admin_user, monkeypatch
):
    h, cid = _create_config_via_api(test_client, monkeypatch, bind_port=7100)
    r = test_client.put(
        f"/api/frp/server-config/{cid}", json={"name": "renamed", "bind_port": None}, headers=h
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["body", "bind_port"], r.text
    stored = _stored(db_session, cid)
    assert (stored.bind_port, stored.name) == (7100, "test-frps")


def test_server_config_update_without_bind_port_keeps_it(
    test_client, db_session, admin_user, monkeypatch
):
    """The other half of the null rejection: the update stays partial. A client
    that leaves bind_port out must neither lose it nor be refused."""
    h, cid = _create_config_via_api(test_client, monkeypatch, bind_port=7100)
    r = test_client.put(f"/api/frp/server-config/{cid}", json={"name": "renamed"}, headers=h)
    assert r.status_code == 200, r.text
    stored = _stored(db_session, cid)
    assert (stored.bind_port, stored.name) == (7100, "renamed")


@pytest.mark.parametrize("field", ["vhost_https_port", "dashboard_port"])
def test_server_config_update_null_still_turns_a_port_off(
    test_client, db_session, admin_user, monkeypatch, field
):
    h, cid = _create_config_via_api(test_client, monkeypatch, **{field: 7443})
    r = test_client.put(f"/api/frp/server-config/{cid}", json={field: None}, headers=h)
    assert r.status_code == 200, r.text
    assert getattr(_stored(db_session, cid), field) is None


def test_server_config_routes_answer_422_for_negative_max_ports(
    test_client, db_session, admin_user, monkeypatch
):
    h = _login(test_client)
    r = test_client.post(
        "/api/frp/server-config",
        json={"name": "test-frps", "server_addr": "frps.example.net", "max_ports_per_client": -1},
        headers=h,
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["body", "max_ports_per_client"], r.text

    h, cid = _create_config_via_api(test_client, monkeypatch, max_ports_per_client=8)
    r = test_client.put(
        f"/api/frp/server-config/{cid}", json={"max_ports_per_client": -1}, headers=h
    )
    assert r.status_code == 422, r.text
    assert _stored(db_session, cid).max_ports_per_client == 8


# R-0533: visitor_port is the bindPort of the tunnel's visitor in the visitor TOML,
# and the desktop's allow-list refuses the whole TOML for a bindPort outside
# 1-65535 (apps/desktop/src-tauri/src/frpc.rs). A value outside fit the INTEGER
# column, so it was stored; 0 was taken as "none" and a free port assigned.
# null and a missing field still mean "the server assigns a free port".
VISITOR_PORTS_OUT_OF_RANGE = (0, -1, 65536, 70000)


@pytest.mark.parametrize("model", [FrpTunnelCreate, FrpTunnelUpdate])
def test_visitor_port_holds_the_port_range(model):
    for ok in (1, 65535, None):
        assert _build(model, visitor_port=ok).visitor_port == ok

    for bad in VISITOR_PORTS_OUT_OF_RANGE:
        with pytest.raises(ValidationError, match="visitor_port"):
            _build(model, visitor_port=bad)


@pytest.mark.parametrize("model", [FrpTunnelCreate, FrpTunnelUpdate])
def test_visitor_port_publishes_the_port_range(model):
    prop = model.model_json_schema()["properties"]["visitor_port"]
    integers = [b for b in prop["anyOf"] if b.get("type") == "integer"]
    assert [(b["minimum"], b["maximum"]) for b in integers] == [(1, 65535)], prop
    assert any(b.get("type") == "null" for b in prop["anyOf"]), prop


def _seed_stcp_tunnel(db):
    db.add(
        FrpServerConfig(
            id="cfg-1",
            name="Default",
            server_addr="frps.example.net",
            bind_port=7000,
            auth_token="secret-frps-auth",
        )
    )
    db.add(Server(id="srv-a", name="serverA", hostname="a.example.test"))
    db.add(
        FrpTunnel(
            id="t-a",
            server_id="srv-a",
            frp_config_id="cfg-1",
            name="a-ssh",
            tunnel_type="stcp",
            protocol="ssh",
            local_port=22,
            secret_key="s" * 32,
            visitor_port=6000,
            enabled=True,
        )
    )
    db.commit()


def _stored_tunnels(db):
    db.expire_all()
    return {t.id: t.visitor_port for t in db.query(FrpTunnel).all()}


def test_tunnel_create_answers_422_outside_the_visitor_port_range(
    test_client, db_session, admin_user
):
    _seed_stcp_tunnel(db_session)
    h = _login(test_client)
    body = {
        "server_id": "srv-a",
        "frp_config_id": "cfg-1",
        "name": "neu",
        "tunnel_type": "stcp",
        "protocol": "ssh",
        "local_port": 22,
    }
    for bad in VISITOR_PORTS_OUT_OF_RANGE:
        r = test_client.post("/api/frp/tunnels", json={**body, "visitor_port": bad}, headers=h)
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["detail"][0]["loc"] == ["body", "visitor_port"], r.text
    assert _stored_tunnels(db_session) == {"t-a": 6000}

    # null still lets the server assign a free port.
    r = test_client.post("/api/frp/tunnels", json={**body, "visitor_port": None}, headers=h)
    assert r.status_code == 201, r.text
    assigned = _stored_tunnels(db_session)[r.json()["id"]]
    assert assigned is not None and 1 <= assigned <= 65535 and assigned != 6000


def test_tunnel_update_holds_the_visitor_port_range(test_client, db_session, admin_user):
    _seed_stcp_tunnel(db_session)
    h = _login(test_client)
    for bad in VISITOR_PORTS_OUT_OF_RANGE:
        r = test_client.put("/api/frp/tunnels/t-a", json={"visitor_port": bad}, headers=h)
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["detail"][0]["loc"] == ["body", "visitor_port"], r.text
        assert _stored_tunnels(db_session) == {"t-a": 6000}

    for edge in (1, 65535):
        r = test_client.put("/api/frp/tunnels/t-a", json={"visitor_port": edge}, headers=h)
        assert r.status_code == 200, (edge, r.text)
        assert _stored_tunnels(db_session) == {"t-a": edge}


# R-0560: local_port goes unchecked into the frpc.toml as localPort, and frpc refuses
# the whole config for a value outside 0-65535, so every tunnel of the host fell over.
# The schema keeps the INTEGER range (contract), the handler holds 1-65535.
def _stored_local_ports(db):
    db.expire_all()
    return {t.id: t.local_port for t in db.query(FrpTunnel).all()}


def test_tunnel_create_answers_422_outside_the_local_port_range(
    test_client, db_session, admin_user
):
    _seed_stcp_tunnel(db_session)
    h = _login(test_client)
    body = {
        "server_id": "srv-a",
        "frp_config_id": "cfg-1",
        "tunnel_type": "stcp",
        "protocol": "ssh",
    }
    for i, bad in enumerate((0, -1, 65536, 70000, 2147483647)):
        r = test_client.post(
            "/api/frp/tunnels", json={**body, "name": f"bad-{i}", "local_port": bad}, headers=h
        )
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["detail"][0]["loc"] == ["body", "local_port"], r.text
    assert _stored_local_ports(db_session) == {"t-a": 22}

    for edge in (1, 65535):
        r = test_client.post(
            "/api/frp/tunnels", json={**body, "name": f"ok-{edge}", "local_port": edge}, headers=h
        )
        assert r.status_code == 201, (edge, r.text)
        assert _stored_local_ports(db_session)[r.json()["id"]] == edge


def test_tunnel_update_holds_the_local_port_range(test_client, db_session, admin_user):
    _seed_stcp_tunnel(db_session)
    h = _login(test_client)
    for bad in (0, 65536, None):
        r = test_client.put("/api/frp/tunnels/t-a", json={"local_port": bad}, headers=h)
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["detail"][0]["loc"] == ["body", "local_port"], r.text
        assert _stored_local_ports(db_session) == {"t-a": 22}

    r = test_client.put("/api/frp/tunnels/t-a", json={"local_port": 65535}, headers=h)
    assert r.status_code == 200, r.text
    assert _stored_local_ports(db_session) == {"t-a": 65535}


def test_tunnel_routes_answer_422_for_a_c1_control_character_in_the_name(
    test_client, db_session, admin_user
):
    _seed_stcp_tunnel(db_session)
    h = _login(test_client)
    body = {
        "server_id": "srv-a",
        "frp_config_id": "cfg-1",
        "name": "neu\x85name",
        "tunnel_type": "stcp",
        "protocol": "ssh",
        "local_port": 22,
    }
    r = test_client.post("/api/frp/tunnels", json=body, headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["body", "name"], r.text
    assert _stored_tunnels(db_session) == {"t-a": 6000}

    r = test_client.put("/api/frp/tunnels/t-a", json={"name": "neu\x85name"}, headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["body", "name"], r.text
    db_session.expire_all()
    assert db_session.get(FrpTunnel, "t-a").name == "a-ssh"


def test_tunnel_routes_answer_422_for_a_plugin_key_in_extra_config(
    test_client, db_session, admin_user
):
    _seed_stcp_tunnel(db_session)
    h = _login(test_client)
    body = {
        "server_id": "srv-a",
        "frp_config_id": "cfg-1",
        "name": "neu",
        "tunnel_type": "stcp",
        "protocol": "ssh",
        "local_port": 22,
        "extra_config": {"plugin.type": "static_file"},
    }
    r = test_client.post("/api/frp/tunnels", json=body, headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["body", "extra_config"], r.text
    assert "'plugin.type'" in r.json()["detail"][0]["msg"], r.text
    assert _stored_tunnels(db_session) == {"t-a": 6000}

    r = test_client.put(
        "/api/frp/tunnels/t-a", json={"extra_config": {"PLUGIN.type": "static_file"}}, headers=h
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["body", "extra_config"], r.text
    db_session.expire_all()
    assert db_session.get(FrpTunnel, "t-a").extra_config is None


# The agent takes a proxy only in the generator's form (apps/agent/internal/frpc/servertoml.go):
# keys of segments [A-Za-z0-9_-]+, no key twice and none a prefix of another, compared without
# regard to case, and TOML integers of 64 bits. A tunnel's extra_config that breaks this cost
# the whole host its config.
REFUSED_EXTRA_CONFIGS = {
    "leading dot": {".a": 1},
    "trailing dot": {"a.": 1},
    "empty segment": {"a..b": 1},
    "int over 64 bits": {"bandwidthLimitMode": 2**63},
    "int under 64 bits": {"bandwidthLimitMode": -(2**63) - 1},
    "a generator key in lower case": {"localport": 2222},
    "a generator key in another case": {"Type": "tcp"},
    "a generator key as a prefix": {"localIP.x": "a"},
    "two keys apart only in case": {"foo": 1, "FOO": 2},
    "one key a prefix of another": {"a": 1, "a.b": 2},
}
TAKEN_EXTRA_CONFIGS = {
    "int at the top": {"bandwidthLimitMode": 2**63 - 1},
    "int at the bottom": {"bandwidthLimitMode": -(2**63)},
    "dotted key": {"transport.useEncryption": True},
    "two keys of a table": {"transport.useEncryption": True, "transport.useCompression": True},
    "plain key": {"bandwidthLimit": "1MB"},
}


@pytest.mark.parametrize("extra", REFUSED_EXTRA_CONFIGS.values(), ids=REFUSED_EXTRA_CONFIGS)
@pytest.mark.parametrize("model", [FrpTunnelCreate, FrpTunnelUpdate])
def test_tunnel_extra_config_holds_the_agents_form(model, extra):
    with pytest.raises(ValidationError) as exc:
        _build(model, extra_config=extra)
    msg = exc.value.errors()[0]["msg"]
    assert any(f"'{key}'" in msg for key in extra), msg


@pytest.mark.parametrize("extra", TAKEN_EXTRA_CONFIGS.values(), ids=TAKEN_EXTRA_CONFIGS)
@pytest.mark.parametrize("model", [FrpTunnelCreate, FrpTunnelUpdate])
def test_tunnel_extra_config_takes_what_the_agent_takes(model, extra):
    assert _build(model, extra_config=extra).extra_config == extra


def test_tunnel_extra_config_check_stays_linear():
    # The body validation runs on the event loop; a check quadratic in the keys took about
    # 10 s for 8000 of them, and nginx lets 10 MB through.
    extra = {f"k{i}.v": i for i in range(20000)}
    start = time.monotonic()
    assert _tunnel(extra_config=extra).extra_config == extra
    assert time.monotonic() - start < 1.0


def test_tunnel_extra_config_check_stays_linear_in_the_key_length():
    # One key of 20000 segments: building every prefix as a string of its own was
    # quadratic in time and memory.
    extra = {".".join(["a"] * 20000): 1}
    start = time.monotonic()
    assert _tunnel(extra_config=extra).extra_config == extra
    assert time.monotonic() - start < 1.0


def test_a_clash_with_a_table_names_one_of_its_keys():
    with pytest.raises(ValidationError) as exc:
        _tunnel(extra_config={"a.b": 1, "a": 2})
    assert "'a' clashes with 'a.b'" in exc.value.errors()[0]["msg"]


def test_the_clash_rule_knows_every_key_the_generator_writes_into_a_proxy():
    # A key the generator starts to write and _GENERATOR_PROXY_KEYS misses would let an
    # extra_config clash with it again, and the agent refuse the whole host.
    tunnels = [
        _stored_tunnel(),
        _stored_tunnel(
            id="t-h",
            name="h-web",
            tunnel_type="https",
            protocol="https",
            custom_domains="a.example.net",
            secret_key=None,
            visitor_port=None,
        ),
    ]
    written = set()
    for proxy in tomllib.loads(generate_frpc_toml(_legacy_row(), tunnels, "srv1"))["proxies"]:
        written |= set(proxy)
    assert written == set(_GENERATOR_PROXY_KEYS)


def test_server_extra_config_keeps_its_allowed_keys():
    for key in ALLOWED_KEYS:
        value = 1 if key != "log.level" else "info"
        assert _config(extra_config={key: value}).extra_config == {key: value}, key


def test_tunnel_routes_answer_422_for_an_extra_config_out_of_the_agents_form(
    test_client, db_session, admin_user
):
    _seed_stcp_tunnel(db_session)
    h = _login(test_client)
    body = {
        "server_id": "srv-a",
        "frp_config_id": "cfg-1",
        "name": "neu",
        "tunnel_type": "stcp",
        "protocol": "ssh",
        "local_port": 22,
    }
    for name, extra in REFUSED_EXTRA_CONFIGS.items():
        r = test_client.post("/api/frp/tunnels", json={**body, "extra_config": extra}, headers=h)
        assert r.status_code == 422, (name, r.text)
        assert r.json()["detail"][0]["loc"] == ["body", "extra_config"], (name, r.text)

        r = test_client.put("/api/frp/tunnels/t-a", json={"extra_config": extra}, headers=h)
        assert r.status_code == 422, (name, r.text)
    assert _stored_tunnels(db_session) == {"t-a": 6000}
    db_session.expire_all()
    assert db_session.get(FrpTunnel, "t-a").extra_config is None


def test_server_route_answers_422_for_a_c1_control_character_in_the_name(
    test_client, db_session, admin_user
):
    h = _login(test_client)
    r = test_client.post(
        "/api/servers", json={"name": "srv\x85name", "hostname": "a.example.test"}, headers=h
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["body", "name"], r.text
    assert db_session.query(Server).count() == 0


# Rows written before T23 never met these bounds; there is no data migration, so
# the generator guards what it reads (Kevin 2026-10-17). frps exits on a port
# outside 0..65535 (pkg/config/v1/validation/common.go ValidatePort, v0.69.1), and
# `bindPort = None` is no TOML at all.
_GENERATOR_LOGGER = "app.modules.frp.config_generator"
_TOKEN = "stored-token-" + "x" * 16
_DASH_PASSWORD = "stored-dash-" + "y" * 16


def _legacy_row(**over):
    """A FrpServerConfig as the DB may still hold it — the schema never saw it."""
    base = dict(
        id="legacy",
        name="legacy",
        server_addr="frps.example.net",
        bind_port=7000,
        auth_token=_TOKEN,
    )
    base.update(over)
    return FrpServerConfig(**base)


def _warnings(caplog, field):
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    for m in messages:
        assert _TOKEN not in m and _DASH_PASSWORD not in m, m
    return [m for m in messages if field in m]


@pytest.mark.parametrize("stored", [None, 0, -1, 65536, 70000])
def test_generator_falls_back_to_7000_for_a_stored_bind_port_out_of_range(stored, caplog):
    cfg = _legacy_row(bind_port=stored)
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        frps = tomllib.loads(generate_frps_toml(cfg))
        frpc = tomllib.loads(generate_frpc_toml(cfg, [], "srv1"))
        visitor = tomllib.loads(generate_visitor_toml(cfg, []))

    assert frps["bindPort"] == 7000
    assert frpc["serverPort"] == 7000
    assert visitor["serverPort"] == 7000
    # One line per generated file, each naming the field and the value used instead.
    warned = _warnings(caplog, "bind_port")
    assert len(warned) == 3, warned
    assert all("7000" in m for m in warned), warned


@pytest.mark.parametrize("stored", [0, -1, 65536, 70000])
@pytest.mark.parametrize(
    "field,key", [("vhost_https_port", "vhostHTTPSPort"), ("dashboard_port", "webServer")]
)
def test_generator_leaves_out_a_stored_optional_port_out_of_range(field, key, stored, caplog):
    cfg = _legacy_row(**{field: stored}, dashboard_user="admin", dashboard_password=_DASH_PASSWORD)
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        frps = tomllib.loads(generate_frps_toml(cfg))

    assert key not in frps, frps
    warned = _warnings(caplog, field)
    assert len(warned) == 1, warned


@pytest.mark.parametrize("stored", [-1, -16])
def test_generator_uses_the_default_for_a_negative_max_ports_per_client(stored, caplog):
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        frps = tomllib.loads(generate_frps_toml(_legacy_row(max_ports_per_client=stored)))

    assert frps["maxPortsPerClient"] == 16
    warned = _warnings(caplog, "max_ports_per_client")
    assert len(warned) == 1 and "16" in warned[0], warned


def test_generator_replaces_all_stored_values_of_one_row(caplog):
    cfg = _legacy_row(
        bind_port=70000,
        vhost_https_port=-443,
        dashboard_port=70000,
        dashboard_password=_DASH_PASSWORD,
        max_ports_per_client=-1,
    )
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        frps = tomllib.loads(generate_frps_toml(cfg))

    assert frps["bindPort"] == 7000
    assert frps["maxPortsPerClient"] == 16
    assert "vhostHTTPSPort" not in frps and "webServer" not in frps
    for field in ("bind_port", "vhost_https_port", "dashboard_port", "max_ports_per_client"):
        assert len(_warnings(caplog, field)) == 1, field


def test_generator_stays_quiet_for_valid_and_unset_values(caplog):
    """The guard must not turn the normal cases into noise: null ports are "off",
    a null or zero max_ports_per_client is the default, and the edges pass."""
    cfg = _legacy_row(
        bind_port=1,
        vhost_https_port=65535,
        dashboard_port=None,
        max_ports_per_client=0,
    )
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        frps = tomllib.loads(generate_frps_toml(cfg))
        frpc = tomllib.loads(generate_frpc_toml(cfg, [], "srv1"))

    assert (frps["bindPort"], frps["vhostHTTPSPort"], frps["maxPortsPerClient"]) == (1, 65535, 16)
    assert "webServer" not in frps
    assert frpc["serverPort"] == 1
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


# A tunnel whose stored extra_config the API refuses today keeps its row; written into
# its proxy, such an entry would make a frpc.toml that does not hold for the whole host.
_PLUGIN_SECRET = "p" * 32


def _stored_tunnel(**over):
    """A FrpTunnel as the DB may still hold it — the schema never saw its extra_config."""
    base = dict(
        id="t-n",
        server_id="srv1",
        frp_config_id="legacy",
        name="n-ssh",
        tunnel_type="stcp",
        protocol="ssh",
        local_ip="127.0.0.1",
        local_port=22,
        secret_key="n" * 32,
        visitor_port=6001,
        enabled=True,
    )
    base.update(over)
    return FrpTunnel(**base)


def _plugin_tunnel(extra_config):
    return _stored_tunnel(
        id="t-p",
        name="p-ssh",
        secret_key=_PLUGIN_SECRET,
        visitor_port=6002,
        extra_config=extra_config,
    )


def _generator_warnings(caplog):
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _GENERATOR_LOGGER and r.levelno == logging.WARNING
    ]


@pytest.mark.parametrize("key", ["plugin.type", "PLUGIN.type", "Plugin.localPath"])
def test_generator_leaves_out_a_stored_tunnel_with_a_plugin_key(key, caplog):
    plugin = _plugin_tunnel(
        json.dumps(
            {"transport.useCompression": True, key: "static_file", "plugin.localPath": "/srv/x"}
        )
    )
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        text = generate_frpc_toml(_legacy_row(), [plugin, _stored_tunnel()], "srv1")

    assert [p["name"] for p in tomllib.loads(text)["proxies"]] == ["n-ssh"]
    assert _PLUGIN_SECRET not in text
    warned = _generator_warnings(caplog)
    assert len(warned) == 1, warned
    assert "'p-ssh'" in warned[0] and f"'{key}'" in warned[0], warned
    assert "transport.useCompression" not in warned[0], warned
    for value in ("static_file", "/srv/x", _PLUGIN_SECRET, _TOKEN):
        assert value not in warned[0], warned


def test_generator_writes_no_proxy_and_no_token_for_only_a_plugin_tunnel(caplog):
    # The column holds JSON text; the generator also takes a dict, and so does the filter.
    plugin = _plugin_tunnel({"plugin": "static_file"})
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        assert active_tunnels([plugin]) == []
        text = generate_frpc_toml(_legacy_row(), [plugin], "srv1")

    frpc = tomllib.loads(text)
    assert "proxies" not in frpc and frpc["auth"] == {"method": "token"}, frpc
    assert _TOKEN not in text and _PLUGIN_SECRET not in text


@pytest.mark.parametrize("key", NOT_PLUGIN_KEYS)
def test_generator_keeps_a_tunnel_with_a_neighbour_of_the_plugin_family(key, caplog):
    tunnel = _stored_tunnel(extra_config=json.dumps({key: True}))
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        frpc = tomllib.loads(generate_frpc_toml(_legacy_row(), [tunnel], "srv1"))

    assert [p["name"] for p in frpc["proxies"]] == ["n-ssh"]
    assert _generator_warnings(caplog) == []


# Rows stored before the key form, the 64-bit bound and the clash rule (REFUSED_EXTRA_CONFIGS):
# the agent would refuse the whole host's config, so only that tunnel is left out. Two keys
# that clash only together are named both.
@pytest.mark.parametrize(
    "extra",
    [
        {".a": 1},
        {"bandwidthLimitMode": 2**63},
        {"localport": 2222},
        {"foo": 1, "FOO": 2},
    ],
    ids=["empty segment", "int over 64 bits", "a generator key", "two keys apart only in case"],
)
def test_generator_leaves_out_a_stored_tunnel_out_of_the_agents_form(extra, caplog):
    refused = _plugin_tunnel(json.dumps(extra))
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        text = generate_frpc_toml(_legacy_row(), [refused, _stored_tunnel()], "srv1")

    assert text == generate_frpc_toml(_legacy_row(), [_stored_tunnel()], "srv1")
    assert [p["name"] for p in tomllib.loads(text)["proxies"]] == ["n-ssh"]
    warned = _generator_warnings(caplog)
    assert len(warned) == 1, warned
    assert "'p-ssh'" in warned[0], warned
    for key, value in extra.items():
        assert repr(key) in warned[0], warned
        assert str(value) not in warned[0], warned


# Stored extra_config the API refuses today (rows from before its checks): by entry, with
# the key the warning names, or as text that is no JSON object, where it names none.
REFUSED_BY_ENTRY = [
    ({" plugin.type": "static_file"}, " plugin.type"),
    ({"plugin .type": "static_file"}, "plugin .type"),
    ({'"plugin".type': "static_file"}, '"plugin".type'),
    ({"x\nplugin.type": "static_file"}, "x\nplugin.type"),
    ({"transport.useCompression": 'x"\nplugin.type = "static_file'}, "transport.useCompression"),
]
NO_JSON_OBJECT = ['{"plugin.type": "static_file"', '["plugin.type"]', "null"]


def _assert_left_out(text):
    proxies = tomllib.loads(text)["proxies"]
    assert [p["name"] for p in proxies] == ["n-ssh"], proxies
    assert not any(k.lower() == "plugin" for p in proxies for k in p), proxies
    assert _PLUGIN_SECRET not in text


def _assert_one_line_without_values(warned):
    assert len(warned) == 1, warned
    assert "'p-ssh'" in warned[0] and "\n" not in warned[0], warned
    for value in ("static_file", "/srv/x", _PLUGIN_SECRET, _TOKEN):
        assert value not in warned[0], warned


@pytest.mark.parametrize("extra,key", REFUSED_BY_ENTRY, ids=repr)
def test_generator_leaves_out_a_stored_tunnel_the_api_would_refuse(extra, key, caplog):
    plugin = _plugin_tunnel(json.dumps({"transport.useCompression": True, **extra}))
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        text = generate_frpc_toml(_legacy_row(), [plugin, _stored_tunnel()], "srv1")

    _assert_left_out(text)
    warned = _generator_warnings(caplog)
    _assert_one_line_without_values(warned)
    assert "entries the API refuses" in warned[0] and repr(key) in warned[0], warned


@pytest.mark.parametrize("stored", NO_JSON_OBJECT, ids=repr)
def test_generator_leaves_out_a_stored_tunnel_whose_extra_config_is_no_object(stored, caplog):
    plugin = _plugin_tunnel(stored)
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        text = generate_frpc_toml(_legacy_row(), [plugin, _stored_tunnel()], "srv1")

    _assert_left_out(text)
    warned = _generator_warnings(caplog)
    _assert_one_line_without_values(warned)
    assert "no JSON object" in warned[0] and "plugin" not in warned[0], warned


STORED_LEFT_OUT = [json.dumps({"plugin.type": "static_file"}), '{"plugin.type": "static_file"']


def _store_extra_config(db, stored):
    _seed_stcp_tunnel(db)
    db.get(FrpTunnel, "t-a").extra_config = stored
    db.commit()


@pytest.mark.parametrize("stored", STORED_LEFT_OUT, ids=repr)
def test_frpc_toml_route_answers_404_for_a_host_whose_only_tunnel_is_left_out(
    stored, test_client, db_session, admin_user
):
    _store_extra_config(db_session, stored)
    r = test_client.get("/api/frp/generate/frpc-toml/srv-a", headers=_login(test_client))
    assert r.status_code == 404, r.text


@pytest.mark.parametrize("stored", STORED_LEFT_OUT, ids=repr)
def test_bulk_zip_writes_no_frpc_toml_for_a_host_whose_only_tunnel_is_left_out(
    stored, test_client, db_session, admin_user, caplog
):
    _store_extra_config(db_session, stored)
    h = _login(test_client)
    with caplog.at_level(logging.WARNING, logger=_GENERATOR_LOGGER):
        r = test_client.get("/api/frp/generate/bulk-zip", headers=h)
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "clients/serverA/frpc.toml" not in zf.namelist(), zf.namelist()
    # Once per tunnel, not per generator call.
    assert len([m for m in _generator_warnings(caplog) if "'a-ssh'" in m]) == 1, caplog.text
    # The visitor TOML carries no extra_config and keeps the visitor, like the visitor routes.
    assert 'name = "a-ssh-visitor"' in zf.read("visitor.toml").decode()


# The raw values a mode="before" validator can be handed. Each one used to reach
# .strip() or the for loop and raise AttributeError/TypeError — not a
# ValidationError, so the six routes that register _validate_tags answered 500.
BAD_TAGS = [
    {"a": 1},  # dict with a str key: the old code iterated it into ["a"], silently
    {1: "a"},  # dict with a non-str key: the key reached .strip() -> AttributeError
    7,  # not iterable at all
    True,  # bool: not iterable either
    "ops",  # a bare string would silently become three one-character tags
    [None],
    [1],
    [["nested"]],
]


@pytest.mark.parametrize("bad", BAD_TAGS)
@pytest.mark.parametrize("model", [FrpTunnelCreate, ServerCreate, ServerUpdate])
def test_tags_rejects_non_string_lists(model, bad):
    build = _tunnel if model is FrpTunnelCreate else lambda **o: model(name="s", hostname="h", **o)
    with pytest.raises(ValidationError):
        build(tags=bad)


def test_tags_still_normalizes_a_real_list():
    """The type check must not cost the normalization the validator exists for."""
    assert _tunnel(tags=["  b  ", "a", "b", "", "x" * 60]).tags == ["b", "a", "x" * 50]


@pytest.mark.parametrize("tags", [True, [{"a": 1}]])
def test_server_route_answers_422_not_500(tags, test_client, db_session, admin_user):
    """The symptom that was measured on six routes: the validator died before a
    response existed.

    Both payloads verified against the unfixed validator: a bool is not iterable
    (TypeError), a dict INSIDE the list reaches .strip() (AttributeError). A dict
    as the whole value does not belong here — JSON object keys are always
    strings, so it arrived as an iterable of strings and answered 201."""
    login = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = test_client.post(
        "/api/servers",
        json={"name": "s1", "hostname": "h1", "tags": tags},
        headers=headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"][-1] == "tags"
