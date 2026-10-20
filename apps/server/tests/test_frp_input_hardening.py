# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FRP input hardening (audit): boundary validation against TOML injection in the
generated frps/frpc/visitor configs, a secret entropy floor, and a fail-closed
allow-list default."""

import logging
import tomllib

import pytest
from pydantic import ValidationError

from app.modules.frp._helpers import get_allow_users
from app.modules.frp.config_generator import (
    generate_frpc_toml,
    generate_frps_toml,
    generate_visitor_toml,
)
from app.modules.frp.models import FrpServerConfig
from app.modules.frp.schemas import (
    FrpServerConfigCreate,
    FrpServerConfigUpdate,
    FrpTunnelCreate,
    FrpTunnelUpdate,
)
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
# T23; the port-range and max-ports tests below hold them.
@pytest.mark.parametrize(
    "model,field",
    [
        (FrpTunnelCreate, "local_port"),
        (FrpTunnelCreate, "visitor_port"),
        (FrpTunnelUpdate, "local_port"),
        (FrpTunnelUpdate, "visitor_port"),
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
