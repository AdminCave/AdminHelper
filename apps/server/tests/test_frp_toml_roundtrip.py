# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Property tests for the FRP config generators: what goes in comes back out.

The generators build TOML by string interpolation, and the only thing standing
between an admin-set field and a broken — or extended — config file is the
validator in schemas.py. Two properties hold that line:

1. Every value the schema ACCEPTS survives generate -> tomllib.loads unchanged.
   If some character got through the validator that TOML reads as syntax, the
   round trip either raises or returns something else than it was given.
2. Every value the schema REJECTS really contains a breaker. The guard may not
   quietly narrow to "no quotes" while backslash or a control character still
   reaches the file.

Hypothesis generates the strings for both directions; the @example pins are the
cases that were reasoned about rather than stumbled upon.
"""

from __future__ import annotations

import json
import tomllib

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.modules.frp.config_generator import (
    generate_frpc_toml,
    generate_frps_toml,
    generate_visitor_toml,
)
from app.modules.frp.extra_config import ALLOWED_KEYS
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.schemas import _TOML_BREAKERS, FrpServerConfigCreate
from app.modules.users.schemas import UserCreate

# U+0080 to U+009F: TOML allows them in a basic string, but the agent refuses every
# frpc.toml line with a control character (unicode.IsControl), so the schema rejects
# them like the other control characters (R-0786).
C1_CONTROLS = [chr(c) for c in range(0x80, 0xA0)]
# What the validator lets through: no quote, no backslash, no control character
# (U+007F included — TOML forbids it in a basic string, so the schema rejects it,
# see test_del_character_is_rejected_by_the_schema; C1_CONTROLS as well). Everything
# else — spaces, '=', '[', '#', unicode — is fair game and must survive.
SAFE_TEXT = st.text(
    alphabet=st.characters(
        blacklist_characters=sorted(_TOML_BREAKERS) + ["\x7f"] + C1_CONTROLS, min_codepoint=0x20
    ),
    min_size=1,
    max_size=40,
)
# What FrpServerConfigCreate takes for the fields of test_frps_toml_round_trips, so every
# example reaches the assertions: on top of SAFE_TEXT no lone surrogate (U+D800 to U+DFFF has
# no UTF-8 form, codec="utf-8" leaves it out) and no `{{` (frp would read it as a template),
# and in a string the frps supervisor checks (auth_token, subdomain_host, a text value of
# extra_config) no brace either: check_config refuses one anywhere in a line.
FRPS_ADDR = st.text(
    alphabet=st.characters(
        blacklist_characters=sorted(_TOML_BREAKERS) + ["\x7f"] + C1_CONTROLS,
        min_codepoint=0x20,
        codec="utf-8",
    ),
    min_size=1,
    max_size=40,
).filter(lambda s: "{{" not in s)
_FRPS_CHAR = st.characters(
    blacklist_characters=sorted(_TOML_BREAKERS) + ["\x7f", "{", "}"] + C1_CONTROLS,
    min_codepoint=0x20,
    codec="utf-8",
)
FRPS_TEXT = st.text(alphabet=_FRPS_CHAR, min_size=1, max_size=40)
FRPS_SECRET = st.text(alphabet=_FRPS_CHAR, min_size=16, max_size=40)
# The schema takes only the extra_config keys the frps supervisor starts frps with
# (frp/extra_config.py).
EXTRA_KEY = st.sampled_from(sorted(ALLOWED_KEYS))
EXTRA_VALUE = st.one_of(
    FRPS_TEXT,
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
)
PORT = st.integers(min_value=1, max_value=65535)
SECRET = st.text(
    # U+007F and C1_CONTROLS excluded for the same reason as in SAFE_TEXT.
    alphabet=st.characters(
        blacklist_characters=sorted(_TOML_BREAKERS) + ["\x7f"] + C1_CONTROLS, min_codepoint=0x20
    ),
    min_size=16,
    max_size=40,
)


def _config(**kw) -> FrpServerConfig:
    """An unattached ORM instance — the generators only read attributes."""
    defaults = dict(
        name="frps",
        server_addr="frps.example.test",
        bind_port=7000,
        vhost_https_port=None,
        auth_token="0123456789abcdef",
        subdomain_host=None,
        max_ports_per_client=None,
        dashboard_port=None,
        dashboard_user=None,
        dashboard_password=None,
        extra_config=None,
    )
    defaults.update(kw)
    return FrpServerConfig(**defaults)


@given(
    server_addr=FRPS_ADDR,
    auth_token=FRPS_SECRET,
    bind_port=PORT,
    subdomain_host=st.one_of(st.none(), FRPS_TEXT),
    extra=st.dictionaries(EXTRA_KEY, EXTRA_VALUE, max_size=5),
)
@example(server_addr="a", auth_token="0123456789abcdef", bind_port=1, subdomain_host="", extra={})
@example(
    server_addr="host = evil",
    auth_token="0123456789abcdef",
    bind_port=7000,
    subdomain_host="[section]",
    extra={"log.level": "v = 2"},
)
@example(
    server_addr="hö…ß",
    auth_token="0123456789abcdef",
    bind_port=7000,
    subdomain_host="ü",
    extra={"log.level": " "},
)
@settings(max_examples=100, deadline=None)
def test_frps_toml_round_trips(server_addr, auth_token, bind_port, subdomain_host, extra):
    # Only values the API would actually accept: the schema is the gate the generator
    # trusts. The strategies generate nothing else, so a rejection is red: it means they
    # and the schema have drifted apart, and the example would assert nothing.
    FrpServerConfigCreate(
        name="frps",
        server_addr=server_addr,
        bind_port=bind_port,
        auth_token=auth_token,
        subdomain_host=subdomain_host,
        extra_config=extra or None,
    )

    cfg = _config(
        server_addr=server_addr,
        bind_port=bind_port,
        auth_token=auth_token,
        subdomain_host=subdomain_host,
        extra_config=json.dumps(extra) if extra else None,
    )
    parsed = tomllib.loads(generate_frps_toml(cfg))

    assert parsed["bindPort"] == bind_port
    assert parsed["auth"]["token"] == auth_token
    assert parsed["auth"]["method"] == "token"
    if subdomain_host:
        assert parsed["subDomainHost"] == subdomain_host
    else:
        assert "subDomainHost" not in parsed
    for key, value in extra.items():
        # A dotted key nests: log.level comes back as parsed["log"]["level"].
        found = parsed
        for part in key.split("."):
            found = found[part]
        assert found == value, (key, found, value)


def _tunnel(**kw) -> FrpTunnel:
    # stcp, not tcp: the schema allows exactly Literal["stcp", "https"], and a type
    # outside it would send every test down the plain branch — past secretKey,
    # allowUsers and customDomains, which are the interpolations that matter here.
    defaults = dict(
        name="tunnel",
        tunnel_type="stcp",
        local_ip="127.0.0.1",
        local_port=22,
        secret_key="0123456789abcdef",
        enabled=True,
        custom_domains=None,
        extra_config=None,
        visitor_port=None,
    )
    defaults.update(kw)
    return FrpTunnel(**defaults)


# allowUsers is filled from User.username (frp/_helpers.py::get_allow_users), and
# those names pass through the users schema, not through the FRP one — so the
# strategy generates what that pattern allows, not arbitrary text.
USERNAME = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="._-"),
    min_size=3,
    max_size=20,
)


@given(
    name=SAFE_TEXT,
    local_ip=SAFE_TEXT,
    local_port=PORT,
    frpc_user=SAFE_TEXT,
    secret=SECRET,
    allow_users=st.lists(USERNAME, min_size=1, max_size=3),
)
@example(
    name="p",
    local_ip="127.0.0.1",
    local_port=22,
    frpc_user="u",
    secret="0123456789abcdef",
    allow_users=["ops-admin"],
)
@settings(max_examples=100, deadline=None)
def test_frpc_stcp_round_trips(name, local_ip, local_port, frpc_user, secret, allow_users):
    """The stcp branch, where the shared secret and the visitor allowlist land."""
    cfg = _config(auth_token=secret)
    tunnel = _tunnel(name=name, local_ip=local_ip, local_port=local_port, secret_key=secret)
    parsed = tomllib.loads(generate_frpc_toml(cfg, [tunnel], frpc_user, allow_users))

    assert parsed["user"] == frpc_user
    assert parsed["auth"]["token"] == secret
    assert len(parsed["proxies"]) == 1
    proxy = parsed["proxies"][0]
    assert proxy["name"] == name
    assert proxy["localIP"] == local_ip
    assert proxy["localPort"] == local_port
    assert proxy["secretKey"] == secret
    assert proxy["allowUsers"] == allow_users


@given(
    name=SAFE_TEXT,
    domains=st.lists(
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters=".-"),
            min_size=1,
            max_size=20,
        ),
        min_size=1,
        max_size=3,
    ),
    secret=SECRET,
)
@example(name="web", domains=["example.test"], secret="0123456789abcdef")
@settings(max_examples=100, deadline=None)
def test_frpc_https_round_trips(name, domains, secret):
    """The https branch: custom_domains is one comma-separated string in the DB and
    becomes a TOML array — the split is the generator's, so the round trip has to
    put the same list back."""
    tunnel = _tunnel(name=name, tunnel_type="https", custom_domains=",".join(domains))
    parsed = tomllib.loads(generate_frpc_toml(_config(auth_token=secret), [tunnel], "u"))

    proxy = parsed["proxies"][0]
    assert proxy["name"] == name
    assert proxy["customDomains"] == domains


@given(name=SAFE_TEXT, visitor_port=PORT, secret=SECRET)
@example(name="v", visitor_port=6000, secret="0123456789abcdef")
@settings(max_examples=50, deadline=None)
def test_visitor_toml_round_trips(name, visitor_port, secret):
    tunnel = _tunnel(name=name, tunnel_type="stcp", secret_key=secret, visitor_port=visitor_port)
    tunnel.target_server = None
    parsed = tomllib.loads(generate_visitor_toml(_config(), [tunnel]))

    assert len(parsed["visitors"]) == 1
    visitor = parsed["visitors"][0]
    assert visitor["name"] == f"{name}-visitor"
    assert visitor["serverName"] == name
    assert visitor["secretKey"] == secret
    assert visitor["bindPort"] == visitor_port


# An extra_config key that collides with a line the generator writes itself ("auth",
# bindPort, webServer.*) is refused by the schema since R-0411:
# test_frp_extra_config.py::test_the_schema_rejects_every_key_the_generator_writes.


def test_allow_users_leaves_out_a_name_the_api_refuses():
    """allowUsers decides who may open an STCP tunnel. _USERNAME_PATTERN in the users
    schema keeps a quote out of new names; a name stored before it (an import, an old
    row) is left out by the generator itself instead of closing the quote."""
    forged = 'mallory", "admin'
    with pytest.raises(ValidationError):
        UserCreate(username=forged, password="correct horse battery")

    tunnel = _tunnel(name="t", secret_key="0123456789abcdef")
    parsed = tomllib.loads(generate_frpc_toml(_config(), [tunnel], "u", [forged, "bob"]))
    assert parsed["proxies"][0]["allowUsers"] == ["bob"]
    parsed = tomllib.loads(generate_frpc_toml(_config(), [tunnel], "u", [forged]))
    assert parsed["proxies"][0]["allowUsers"] == ["ops-admin"], "fail closed, not open"


def test_a_server_name_the_api_refuses_gets_no_user_and_no_tunnel():
    """The frpc user is the server name; one stored before the schema check must not
    reach the TOML, and without it no proxy can be named after it either."""
    tunnel = _tunnel(name="t", secret_key="0123456789abcdef")
    parsed = tomllib.loads(generate_frpc_toml(_config(), [tunnel], 'web"\nx = "1', ["bob"]))
    assert "user" not in parsed
    assert parsed.get("proxies", []) == []


def test_a_visitor_user_the_api_refuses_is_an_error():
    with pytest.raises(ValueError):
        generate_visitor_toml(_config(), [], 'eve"')


@given(
    text=st.text(min_size=1, max_size=30),
    breaker=st.sampled_from(
        sorted(_TOML_BREAKERS) + ["\x00", "\x1f", "\t", "\x7f", "\x80", "\x85", "\x9f"]
    ),
    position=st.integers(min_value=0, max_value=30),
)
@example(text="host", breaker='"', position=0)
@example(text="host", breaker="\\", position=4)
@example(text="host", breaker="\n", position=2)
@settings(max_examples=100, deadline=None)
def test_every_breaker_is_rejected(text, breaker, position):
    """The other direction: a string carrying a breaker never passes the schema.

    Without this the round-trip property above would still hold for a validator
    that had quietly stopped rejecting anything — it only ever sees accepted
    values.
    """
    position = min(position, len(text))
    poisoned = text[:position] + breaker + text[position:]

    with pytest.raises(ValidationError):
        FrpServerConfigCreate(name="frps", server_addr=poisoned, auth_token="0123456789abcdef")


def test_del_character_is_rejected_by_the_schema():
    """TOML forbids U+007F in a basic string like the other control characters: in
    the generated frps.toml it would leave a file frps cannot read. The schema
    rejects it with the same message."""
    # auth_token, not server_addr: frps.toml carries the token, while server_addr
    # only ever reaches the frpc and visitor files.
    poisoned = "0123456789abcde\x7f"  # 16 chars, so _check_secret's floor is met
    with pytest.raises(ValidationError, match="unzulässige Zeichen"):
        FrpServerConfigCreate(name="frps", server_addr="frps.example.test", auth_token=poisoned)
