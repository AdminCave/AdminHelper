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
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.schemas import _TOML_BREAKERS, FrpServerConfigCreate

# What the validator lets through: no quote, no backslash, no control character.
# Everything else — spaces, '=', '[', '#', unicode — is fair game and must survive.
# U+007F is excluded here although the validator DOES let it through: TOML forbids
# it in a basic string, so it produces a file frps cannot parse. That gap is a
# finding of this suite, pinned in test_del_character_breaks_the_generated_toml
# below rather than re-discovered as a random failure in every other property.
SAFE_TEXT = st.text(
    alphabet=st.characters(
        blacklist_characters=sorted(_TOML_BREAKERS) + ["\x7f"], min_codepoint=0x20
    ),
    min_size=1,
    max_size=40,
)
# Keys are emitted unquoted, so the schema demands TOML bare keys. A dot would
# nest the key ({"a": {"b": …}}) and a name the generator itself writes (auth,
# webServer, transport) would collide with that fixed line — both are about the
# generator's own layout, not about the round trip this test is for.
_RESERVED = {"auth", "webServer", "transport", "bindPort", "serverAddr", "serverPort", "user"}
EXTRA_KEY = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
).filter(lambda k: k not in _RESERVED)
EXTRA_VALUE = st.one_of(
    SAFE_TEXT,
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
)
PORT = st.integers(min_value=1, max_value=65535)
SECRET = st.text(
    # U+007F excluded for the same reason as in SAFE_TEXT — the gap belongs to
    # its own pinned test, not to every secret this suite generates.
    alphabet=st.characters(
        blacklist_characters=sorted(_TOML_BREAKERS) + ["\x7f"], min_codepoint=0x20
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
    server_addr=SAFE_TEXT,
    auth_token=SECRET,
    bind_port=PORT,
    subdomain_host=st.one_of(st.none(), SAFE_TEXT),
    extra=st.dictionaries(EXTRA_KEY, EXTRA_VALUE, max_size=5),
)
@example(server_addr="a", auth_token="0123456789abcdef", bind_port=1, subdomain_host="", extra={})
@example(
    server_addr="host = evil",
    auth_token="0123456789abcdef",
    bind_port=7000,
    subdomain_host="[section]",
    extra={"k": "v = 2"},
)
@example(
    server_addr="hö…ß",
    auth_token="0123456789abcdef",
    bind_port=7000,
    subdomain_host="ü",
    extra={"a": " "},
)
@settings(max_examples=100, deadline=None)
def test_frps_toml_round_trips(server_addr, auth_token, bind_port, subdomain_host, extra):
    # Only values the API would actually accept: the schema is the gate the
    # generator trusts, so a value it rejects says nothing about the generator.
    try:
        FrpServerConfigCreate(
            name="frps",
            server_addr=server_addr,
            bind_port=bind_port,
            auth_token=auth_token,
            subdomain_host=subdomain_host,
            extra_config=extra or None,
        )
    except ValidationError:
        return

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
        assert parsed[key] == value, (key, parsed[key], value)


def _tunnel(**kw) -> FrpTunnel:
    defaults = dict(
        name="tunnel",
        tunnel_type="tcp",
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


@given(
    name=SAFE_TEXT,
    local_ip=SAFE_TEXT,
    local_port=PORT,
    frpc_user=SAFE_TEXT,
    secret=SECRET,
)
@example(name="p", local_ip="127.0.0.1", local_port=22, frpc_user="u", secret="0123456789abcdef")
@settings(max_examples=100, deadline=None)
def test_frpc_toml_round_trips(name, local_ip, local_port, frpc_user, secret):
    # No breaker case here: SAFE_TEXT cannot produce one, and what the schema
    # rejects is the subject of test_every_breaker_is_rejected below.
    cfg = _config(auth_token=secret)
    toml = generate_frpc_toml(
        cfg, [_tunnel(name=name, local_ip=local_ip, local_port=local_port)], frpc_user
    )
    parsed = tomllib.loads(toml)

    assert parsed["user"] == frpc_user
    assert parsed["auth"]["token"] == secret
    assert len(parsed["proxies"]) == 1
    proxy = parsed["proxies"][0]
    assert proxy["name"] == name
    assert proxy["localIP"] == local_ip
    assert proxy["localPort"] == local_port


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


@pytest.mark.xfail(
    strict=True,
    reason="_reject_toml_breakers rejects ord(c) < 0x20 but not U+007F, which TOML "
    "forbids in a basic string just the same — the generated file then does not parse",
)
def test_del_character_breaks_the_generated_toml():
    """U+007F passes the schema and produces TOML that tomllib refuses.

    Held as a strict xfail on purpose: the moment the validator learns about
    U+007F this test XPASSes and fails the suite, which is the reminder to delete
    it. Pure availability, not injection — DEL cannot close a string or open a
    section, it only makes the file unreadable for frps.
    """
    # auth_token, not server_addr: frps.toml carries the token, while server_addr
    # only ever reaches the frpc and visitor files.
    poisoned = "0123456789abcde\x7f"  # 16 chars, so _check_secret's floor is met
    accepted = FrpServerConfigCreate(
        name="frps", server_addr="frps.example.test", auth_token=poisoned
    )
    assert accepted.auth_token == poisoned  # the schema let it through

    toml = generate_frps_toml(_config(auth_token=accepted.auth_token))
    tomllib.loads(toml)  # raises TOMLDecodeError -> the xfail


@given(
    text=st.text(min_size=1, max_size=30),
    breaker=st.sampled_from(sorted(_TOML_BREAKERS) + ["\x00", "\x1f", "\t"]),
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
