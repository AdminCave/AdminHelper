# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""extra_config of the FRP server config holds only what the frps supervisor starts frps with
(frp/extra_config.py, R-0411).

The allowed keys are TOP_KEYS of apps/frps/frps-supervisor.sh without the keys the generator
writes itself, and a value is allowed exactly when the line the generator writes for it follows
check_config's grammar; both are read from the script here. The API answers 422 for any other
key or value. At its start the server removes them from the configs it already holds, logs the
keys (never the values) and tells the admins once per config in the bell; a second start
changes nothing.

The string fields the generator writes into frps.toml (subdomain host, dashboard user and
password, auth token) follow the same value rule; the API answers 422 for a brace there too.
A stored value that breaks it cannot be cleaned (a token has no sensible replacement): the
start tells the admins once which fields to set anew, naming the field, never the value.

A lone surrogate (U+D800 to U+DFFF) has no UTF-8 form, so no frps.toml can carry it: the API
answers 422 for one in extra_config or in a string field, and the start removes such an
extra_config value. The start also names the other values check_config refuses and the start
does not change: an auth token under 16 bytes and a dashboard port that is 443, the bind port
or FRP_BIND_PORT. The bell names each field with its rule, never the value."""

import json
import logging
import math
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.frp.config_generator import generate_frps_toml
from app.modules.frp.extra_config import ALLOWED_KEYS, STRING_FIELDS, value_allowed
from app.modules.frp.models import FrpServerConfig
from app.modules.frp.schemas import FrpServerConfigCreate, FrpServerConfigUpdate
from app.modules.notifications.models import Notification

SCRIPT = Path(__file__).resolve().parents[2] / "frps" / "frps-supervisor.sh"
TABLE = "[transport.tls]"

# Every field the generator writes a top-level line for.
FULL = {
    "vhost_https_port": 8443,
    "subdomain_host": "example.net",
    "max_ports_per_client": 8,
    "dashboard_port": 7500,
    "dashboard_user": "admin",
    "dashboard_password": "d" * 24,
}
# Every allowed key.
ALLOWED = {
    "transport.maxPoolCount": 5,
    "transport.tcpMux": True,
    "transport.tcpMuxKeepaliveInterval": 30,
    "transport.heartbeatTimeout": -1,
    "transport.tcpKeepalive": 7200,
    "userConnTimeout": 10,
    "log.level": "info",
    "log.maxDays": 3,
}
NOT_ALLOWED = {
    "log.to": "/var/log/frps.log",
    "enablePrometheus": True,
    "transport.tls.force": False,
    # Written by the generator: always, and from dashboard_port.
    "auth.additionalScopes": "HeartBeats",
    "webServer.port": 7500,
    # A generator key and an allowed key in another case.
    "BindPort": 7001,
    "Log.Level": "debug",
}
MODELS = [FrpServerConfigCreate, FrpServerConfigUpdate]
# Long enough for the token and password floor, and a brace check_config refuses.
BRACED = "a" * 16 + "{x}"


def _script() -> str:
    return SCRIPT.read_text()


def _top_keys() -> set[str]:
    match = re.search(r'^TOP_KEYS="([^"]*)"', _script(), re.M)
    assert match, "TOP_KEYS not found in the supervisor"
    return set(match[1].split())


def _passes_check_config_lines(toml: str) -> bool:
    """check_config's rules for the lines of a file: no byte but newline, printable ASCII and
    0x80-0xff; every line empty, the table, or `key = value` in its pattern without a brace or
    a backslash. Lines split at newline only, as awk splits them."""
    match = re.search(r"\$0 !~ /(.+)/ \{$", _script(), re.M)
    assert match, "the line pattern of check_config not found in the supervisor"
    pattern = re.compile(match[1])
    if any(b != 0x0A and (b < 0x20 or b == 0x7F) for b in toml.encode()):
        return False
    return all(
        line in ("", TABLE)
        or (not any(c in line for c in "{}\\") and pattern.fullmatch(line) is not None)
        for line in toml.split("\n")
    )


def _config(**fields) -> FrpServerConfig:
    values = {
        "id": "cfg",
        "name": "frps",
        "server_addr": "frps.example.net",
        "bind_port": 7000,
        "auth_token": "t" * 32,
    }
    values.update(fields)
    return FrpServerConfig(**values)


def _build(model, **fields):
    if model is FrpServerConfigCreate:
        return model(name="frps", server_addr="frps.example.net", **fields)
    return model(**fields)


# --- the list and the grammar, against the script ---


def _top_level_keys(toml: str) -> set[str]:
    return {line.split(" = ")[0] for line in toml.split(TABLE)[0].splitlines() if line}


GENERATED_KEYS = _top_level_keys(generate_frps_toml(_config(**FULL)))


def test_the_allowed_keys_are_the_top_keys_the_generator_does_not_write():
    generated = GENERATED_KEYS

    assert generated | ALLOWED_KEYS == _top_keys()
    # Not even in another case: the supervisor counts bindport next to bindPort as a key twice.
    assert {key.lower() for key in generated}.isdisjoint(key.lower() for key in ALLOWED_KEYS)


def test_the_string_fields_are_the_quoted_lines_the_generator_writes_from_the_config():
    toml = generate_frps_toml(_config(**FULL))
    quoted = {
        line.split(" = ")[0]
        for line in toml.split(TABLE)[0].splitlines()
        if line and line.split(" = ")[1].startswith('"')
    }
    # Fixed strings, not fields.
    assert quoted - {"auth.method", "webServer.addr"} == set(STRING_FIELDS)
    for key, field in STRING_FIELDS.items():
        assert f'{key} = "{getattr(_config(**FULL), field)}"' in toml


VALUES = [
    True,
    False,
    0,
    -1,
    2**63,
    1.5,
    -0.0,
    1e-07,
    1e300,
    math.nan,
    math.inf,
    -math.inf,
    "info",
    "",
    "ü",
    # The neighbours of the surrogates.
    "\ud7ff",
    "\ue000",
    "a b = c",
    "[x] # y",
    "a\x85b",
    "a{b",
    "b}",
    "{{print}}",
    "a\\b",
    'a"b',
    "a\tb",
    "a\nb",
    "a\x00b",
    "a\x7fb",
    None,
    [1],
    {"a": 1},
]


@pytest.mark.parametrize("value", VALUES, ids=repr)
def test_a_value_is_allowed_exactly_when_its_line_passes_check_config(value):
    toml = generate_frps_toml(_config(extra_config=json.dumps({"log.level": value})))
    assert _passes_check_config_lines(generate_frps_toml(_config()))
    assert value_allowed(value) is _passes_check_config_lines(toml)


SURROGATES = ["\ud800", "a\udfffb", "\udc80" + "a" * 16]


@pytest.mark.parametrize("value", SURROGATES, ids=repr)
def test_a_lone_surrogate_is_not_allowed_as_no_frps_toml_can_carry_it(value):
    assert value_allowed(value) is False
    toml = generate_frps_toml(_config(extra_config=json.dumps({"log.level": value})))
    with pytest.raises(UnicodeEncodeError):
        toml.encode("utf-8")


# --- the schema ---


@pytest.mark.parametrize("model", MODELS)
def test_the_schema_takes_every_allowed_key(model):
    assert _build(model, extra_config=ALLOWED).extra_config == ALLOWED
    edges = {"log.level": "ü [x] # y", "userConnTimeout": 1.5, "log.maxDays": -0.0}
    assert _build(model, extra_config=edges).extra_config == edges


@pytest.mark.parametrize("key", list(NOT_ALLOWED))
@pytest.mark.parametrize("model", MODELS)
def test_the_schema_rejects_any_other_key(model, key):
    with pytest.raises(ValidationError, match="is not allowed"):
        _build(model, extra_config={"log.level": "info", key: NOT_ALLOWED[key]})


@pytest.mark.parametrize("key", sorted(GENERATED_KEYS | {"auth"}))
@pytest.mark.parametrize("model", MODELS)
def test_the_schema_rejects_every_key_the_generator_writes(model, key):
    # Such a key would stand in frps.toml twice ("auth" as a value next to the auth table),
    # which neither TOML nor the supervisor accepts.
    with pytest.raises(ValidationError, match="is not allowed"):
        _build(model, extra_config={key: "x"})


# `{{` is refused earlier, by the guard of every TOML string (test_frp_input_hardening.py).
@pytest.mark.parametrize("value", ["{print}", "a}", math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("model", MODELS)
def test_the_schema_rejects_a_value_check_config_rejects(model, value):
    with pytest.raises(ValidationError, match="extra_config value"):
        _build(model, extra_config={"log.level": value})


@pytest.mark.parametrize("field", list(STRING_FIELDS.values()))
@pytest.mark.parametrize("model", MODELS)
def test_the_schema_rejects_a_brace_in_a_string_field_of_frps_toml(model, field):
    for value in (BRACED, "a" * 16 + "}"):
        with pytest.raises(ValidationError, match="braces"):
            _build(model, **{field: value})
    # Nothing more than check_config refuses.
    fine = "\u00fc [x] # y = z " + "a" * 16
    assert getattr(_build(model, **{field: fine}), field) == fine


@pytest.mark.parametrize("value", SURROGATES, ids=repr)
@pytest.mark.parametrize("model", MODELS)
def test_the_schema_rejects_a_lone_surrogate(model, value):
    with pytest.raises(ValidationError, match="surrogate"):
        _build(model, extra_config={"log.level": value})
    for field in STRING_FIELDS.values():
        with pytest.raises(ValidationError, match="surrogate"):
            _build(model, **{field: value + "a" * 16})


def _login(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def api(test_client, admin_user, monkeypatch):
    import app.modules.frp.config_router as cr

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    return SimpleNamespace(client=test_client, headers=_login(test_client))


def _post(api, extra):
    body = {"name": "frps", "server_addr": "frps.example.net", "extra_config": extra}
    return api.client.post("/api/frp/server-config", json=body, headers=api.headers)


def _stored_extra(db, config_id):
    config = db.get(FrpServerConfig, config_id)
    db.refresh(config)
    return json.loads(config.extra_config) if config.extra_config else None


def test_post_answers_422_for_a_key_not_allowed(api, db_session):
    for key, value in NOT_ALLOWED.items():
        r = _post(api, {"log.level": "info", key: value})
        assert r.status_code == 422, (key, r.text)
    assert db_session.query(FrpServerConfig).count() == 0

    created = _post(api, ALLOWED)
    assert created.status_code == 201, created.text
    assert _stored_extra(db_session, created.json()["id"]) == ALLOWED


def test_post_and_put_answer_422_for_a_brace_in_a_string_field(api, db_session):
    for field in STRING_FIELDS.values():
        r = api.client.post(
            "/api/frp/server-config",
            json={"name": "frps", "server_addr": "frps.example.net", field: BRACED},
            headers=api.headers,
        )
        assert r.status_code == 422, (field, r.text)
    assert db_session.query(FrpServerConfig).count() == 0

    created = _post(api, None)
    assert created.status_code == 201, created.text
    config_id = created.json()["id"]
    for field in STRING_FIELDS.values():
        r = api.client.put(
            f"/api/frp/server-config/{config_id}", json={field: BRACED}, headers=api.headers
        )
        assert r.status_code == 422, (field, r.text)
    stored = db_session.get(FrpServerConfig, config_id)
    db_session.refresh(stored)
    assert BRACED not in [getattr(stored, field) for field in STRING_FIELDS.values()]


def test_put_answers_422_for_a_key_or_value_not_allowed(api, db_session):
    created = _post(api, {"log.level": "info"})
    assert created.status_code == 201, created.text
    url = f"/api/frp/server-config/{created.json()['id']}"

    for extra in [*({key: value} for key, value in NOT_ALLOWED.items()), {"log.level": "{x}"}]:
        r = api.client.put(url, json={"extra_config": extra}, headers=api.headers)
        assert r.status_code == 422, (extra, r.text)
    assert _stored_extra(db_session, created.json()["id"]) == {"log.level": "info"}

    r = api.client.put(url, json={"extra_config": ALLOWED}, headers=api.headers)
    assert r.status_code == 200, r.text
    assert _stored_extra(db_session, created.json()["id"]) == ALLOWED


def test_post_and_put_answer_422_for_a_lone_surrogate(api, db_session):
    def send(method, url, body):
        # Only a JSON escape spells a lone surrogate on the wire; it has no UTF-8 form.
        content = json.dumps(body)
        assert "\\ud800" in content
        headers = {**api.headers, "Content-Type": "application/json"}
        return api.client.request(method, url, content=content, headers=headers)

    url = "/api/frp/server-config"
    # RequestModel refuses the surrogate before any field validator, at the string itself:
    # inside extra_config that is the key it stands under.
    bad = [
        ({"extra_config": {"log.level": "a\ud800b"}}, ["body", "extra_config", "log.level"]),
        *(({field: "\ud800" + "a" * 16}, ["body", field]) for field in STRING_FIELDS.values()),
    ]
    for fields, loc in bad:
        r = send("POST", url, {"name": "frps", "server_addr": "frps.example.net", **fields})
        assert r.status_code == 422, (fields, r.text)
        assert r.json()["detail"][0]["loc"] == loc, r.text
    assert db_session.query(FrpServerConfig).count() == 0

    created = _post(api, {"log.level": "info"})
    assert created.status_code == 201, created.text
    config_id = created.json()["id"]
    for fields, loc in bad:
        r = send("PUT", f"{url}/{config_id}", fields)
        assert r.status_code == 422, (fields, r.text)
        assert r.json()["detail"][0]["loc"] == loc, r.text
    assert _stored_extra(db_session, config_id) == {"log.level": "info"}

    # A 422 whose input has a UTF-8 form carries it unescaped.
    r = api.client.put(f"{url}/{config_id}", json={"subdomain_host": "ü{x}"}, headers=api.headers)
    assert r.status_code == 422, r.text
    assert "ü{x}".encode() in r.content


# --- the start of the server ---

STORED = {
    "log.level": "info",
    "transport.tcpMux": True,
    "log.to": "/var/log/frps.log",
    "enablePrometheus": True,
    "log.maxDays": math.nan,
    "userConnTimeout": "{{print}}",
}
KEPT = {"log.level": "info", "transport.tcpMux": True}
REMOVED = ["log.to", "enablePrometheus", "log.maxDays", "userConnTimeout"]


def _notices(db) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(Notification.source_type == "frp_config")
        .order_by(Notification.id)
        .all()
    )


def _clean(db, caplog) -> str:
    import app.main as m

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.main"):
        m._check_frps_server_configs(db)
    return caplog.text


def test_startup_removes_only_what_frps_is_not_started_with_and_tells_the_admins_once(
    db_session, admin_user, normal_user, caplog
):
    db_session.add(_config(id="cfg-old", extra_config=json.dumps(STORED)))
    db_session.commit()

    log = _clean(db_session, caplog)

    assert _stored_extra(db_session, "cfg-old") == KEPT
    toml = generate_frps_toml(db_session.get(FrpServerConfig, "cfg-old"))
    assert _passes_check_config_lines(toml)
    assert _top_level_keys(toml) <= _top_keys()
    notices = _notices(db_session)
    assert [(n.user_id, n.source_id, n.severity) for n in notices] == [
        (admin_user.id, "cfg-old", "warning")
    ]
    for key in REMOVED:
        assert key in notices[0].body
        assert key in log
    for value in ("/var/log/frps.log", "{{print}}"):
        assert value not in notices[0].body
        assert value not in log

    log = _clean(db_session, caplog)

    assert _stored_extra(db_session, "cfg-old") == KEPT
    assert len(_notices(db_session)) == 1
    assert log == ""


def test_startup_tells_once_per_cleaned_config_and_leaves_a_clean_one_alone(
    db_session, admin_user, caplog
):
    clean = json.dumps(ALLOWED)
    db_session.add_all(
        [
            _config(id="cfg-clean", extra_config=clean),
            _config(id="cfg-some", extra_config=json.dumps(STORED)),
            _config(id="cfg-all", extra_config=json.dumps({"log.to": "/var/log/frps.log"})),
            _config(id="cfg-none"),
        ]
    )
    db_session.commit()

    _clean(db_session, caplog)
    _clean(db_session, caplog)

    assert db_session.get(FrpServerConfig, "cfg-clean").extra_config == clean
    assert _stored_extra(db_session, "cfg-some") == KEPT
    assert db_session.get(FrpServerConfig, "cfg-all").extra_config is None
    assert db_session.get(FrpServerConfig, "cfg-none").extra_config is None
    assert sorted(n.source_id for n in _notices(db_session)) == ["cfg-all", "cfg-some"]


def test_startup_goes_on_when_a_config_cannot_be_read(db_session, admin_user, caplog):
    db_session.add_all(
        [
            _config(id="cfg-broken", extra_config="{not json"),
            _config(id="cfg-other", extra_config=json.dumps(STORED), subdomain_host=BRACED),
        ]
    )
    db_session.commit()

    log = _clean(db_session, caplog)

    assert "JSONDecodeError" in log
    assert db_session.get(FrpServerConfig, "cfg-broken").extra_config == "{not json"
    assert _stored_extra(db_session, "cfg-other") == KEPT
    assert [n.source_id for n in _notices(db_session)] == ["cfg-other", "cfg-other:subdomain_host"]


def test_startup_removes_an_extra_config_value_no_frps_toml_can_carry(
    db_session, admin_user, caplog
):
    # extra_config is stored as JSON text, which spells a lone surrogate as an escape.
    stored = json.dumps({"log.level": "a\ud800b", "transport.tcpMux": True})
    assert "\\ud800" in stored
    db_session.add(_config(id="cfg-surrogate", extra_config=stored))
    db_session.commit()

    log = _clean(db_session, caplog)

    assert _stored_extra(db_session, "cfg-surrogate") == {"transport.tcpMux": True}
    toml = generate_frps_toml(db_session.get(FrpServerConfig, "cfg-surrogate"))
    assert _passes_check_config_lines(toml)
    notices = _notices(db_session)
    assert [n.source_id for n in notices] == ["cfg-surrogate"]
    assert "log.level" in notices[0].body
    assert "log.level" in log


def test_startup_tells_the_admins_once_which_fields_to_set_anew(
    db_session, admin_user, normal_user, caplog
):
    fields = {"auth_token": BRACED, "subdomain_host": BRACED, "dashboard_password": BRACED}
    db_session.add_all(
        [
            _config(id="cfg-fields", dashboard_port=7500, dashboard_user="admin", **fields),
            # Without a dashboard port its fields are not in frps.toml.
            _config(id="cfg-no-dashboard", dashboard_user=BRACED, dashboard_password=BRACED),
        ]
    )
    db_session.commit()

    log = _clean(db_session, caplog)

    notices = _notices(db_session)
    assert [(n.user_id, n.source_id, n.severity) for n in notices] == [
        (admin_user.id, "cfg-fields:subdomain_host,dashboard_password,auth_token", "warning")
    ]
    for label in ("Subdomain Host", "Dashboard Passwort", "Auth Token"):
        assert label in notices[0].body
    assert "Dashboard User" not in notices[0].body
    for field in fields:
        assert field in log
    assert BRACED not in notices[0].body + notices[0].title
    assert BRACED not in log
    stored = db_session.get(FrpServerConfig, "cfg-fields")
    assert {field: getattr(stored, field) for field in fields} == fields

    _clean(db_session, caplog)

    assert len(_notices(db_session)) == 1

    # Another set of fields is news again; none at all is quiet.
    stored.subdomain_host = "example.net"
    db_session.commit()
    _clean(db_session, caplog)
    assert [n.source_id for n in _notices(db_session)][1:] == [
        "cfg-fields:dashboard_password,auth_token"
    ]
    stored.auth_token = stored.dashboard_password = "t" * 32
    db_session.commit()
    assert _clean(db_session, caplog) == ""
    assert len(_notices(db_session)) == 2

    stored.dashboard_user = BRACED
    db_session.commit()
    _clean(db_session, caplog)
    notices = _notices(db_session)
    assert [n.source_id for n in notices][2:] == ["cfg-fields:dashboard_user"]
    assert notices[2].body.endswith(f"Bitte neu setzen: Dashboard User ({CHARACTERS}).")


# The rules as the bell names them.
CHARACTERS = "ohne Anführungszeichen, Backslash, geschweifte Klammern und Steuerzeichen"
TOKEN = "mindestens 16 Zeichen"
DASHBOARD = "weder 443 noch der Bind Port noch FRP_BIND_PORT"


def test_startup_tells_the_admins_once_about_a_token_frps_is_not_started_with(
    db_session, admin_user, caplog
):
    short = "s" * 15
    db_session.add_all(
        [
            _config(id="cfg-short", auth_token=short),
            # frps is not started with an empty token either; the row keeps it.
            _config(id="cfg-empty", auth_token=""),
            _config(id="cfg-16", auth_token="t" * 16),
            # check_config counts bytes (LC_ALL=C): eight two-byte characters are 16.
            _config(id="cfg-bytes", auth_token="é" * 8),
        ]
    )
    db_session.commit()

    log = _clean(db_session, caplog)

    # The start reads the configs in no set order.
    notices = sorted(_notices(db_session), key=lambda n: n.source_id)
    assert [(n.user_id, n.source_id, n.severity) for n in notices] == [
        (admin_user.id, "cfg-empty:auth_token", "warning"),
        (admin_user.id, "cfg-short:auth_token", "warning"),
    ]
    for notice in notices:
        assert notice.body.endswith(f"Bitte neu setzen: Auth Token ({TOKEN}).")
        assert short not in notice.body + notice.title
    assert "auth_token" in log
    assert "cfg-empty" in log
    assert short not in log
    assert db_session.get(FrpServerConfig, "cfg-short").auth_token == short
    assert db_session.get(FrpServerConfig, "cfg-empty").auth_token == ""

    _clean(db_session, caplog)

    assert len(_notices(db_session)) == 2


@pytest.mark.parametrize("dashboard_port", [443, 7100, 7200], ids=["443", "bind", "published"])
def test_startup_tells_the_admins_once_about_a_dashboard_port_frps_refuses(
    dashboard_port, db_session, admin_user, caplog, monkeypatch
):
    import app.main as m

    monkeypatch.setattr(m, "FRP_BIND_PORT", 7200)
    db_session.add_all(
        [
            _config(id="cfg-port", bind_port=7100, dashboard_port=dashboard_port),
            _config(id="cfg-fine", bind_port=7100, dashboard_port=7500),
            # Without a dashboard port frps.toml has no webServer.port.
            _config(id="cfg-none", bind_port=7100),
        ]
    )
    db_session.commit()

    log = _clean(db_session, caplog)
    _clean(db_session, caplog)

    notices = _notices(db_session)
    assert [(n.user_id, n.source_id, n.severity) for n in notices] == [
        (admin_user.id, "cfg-port:dashboard_port", "warning")
    ]
    assert notices[0].body.endswith(f"Bitte neu setzen: Dashboard Port ({DASHBOARD}).")
    assert "dashboard_port" in log
    for value in ("7100", "7200"):
        assert value not in notices[0].body + notices[0].title + log


def test_startup_names_every_field_with_its_rule_in_one_notice(
    db_session, admin_user, caplog, monkeypatch
):
    import app.main as m

    monkeypatch.setattr(m, "FRP_BIND_PORT", 7000)
    db_session.add(
        _config(id="cfg-all", subdomain_host=BRACED, auth_token="short", dashboard_port=7000)
    )
    db_session.commit()

    _clean(db_session, caplog)

    notices = _notices(db_session)
    assert [n.source_id for n in notices] == ["cfg-all:subdomain_host,auth_token,dashboard_port"]
    assert notices[0].body.endswith(
        f"Bitte neu setzen: Subdomain Host ({CHARACTERS}), Auth Token ({TOKEN}), "
        f"Dashboard Port ({DASHBOARD})."
    )


def test_every_string_field_has_its_label_for_the_bell():
    import app.main as m

    # A field without one would end the check with a KeyError, and nobody would be told.
    assert set(m._FRPS_FIELD_LABELS) == set(STRING_FIELDS.values()) | {"dashboard_port"}


def test_startup_checks_the_configs_before_it_writes_frps_toml(monkeypatch):
    import app.main as m

    calls = []
    monkeypatch.setattr(m, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(m, "_ensure_admin", lambda db: calls.append("admin"))
    monkeypatch.setattr(m, "_check_frps_server_configs", lambda db: calls.append("check"))
    monkeypatch.setattr(m, "_ensure_frps_config", lambda db: calls.append("write"))

    m._run_startup_tasks()

    assert calls == ["admin", "check", "write"]
