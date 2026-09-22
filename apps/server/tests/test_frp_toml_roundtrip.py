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
from app.modules.users.schemas import UserCreate

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
# Keys are emitted unquoted, so the schema demands TOML bare keys. Two shapes are
# kept out of the round-trip property on purpose: a dot nests the key
# ({"a": {"b": …}}), and a name the generator also writes itself collides with that
# fixed line — the collision is a finding in its own right and has its own pinned
# test below, rather than being re-derived as a random failure here.
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


@pytest.mark.xfail(
    strict=True,
    # raises= is what makes the reminder work: without it ANY exception counts as
    # the expected failure, so once the validator learns about U+007F the
    # ValidationError from the line above would keep this test quietly xfailing
    # forever instead of turning XPASS and asking to be deleted.
    raises=tomllib.TOMLDecodeError,
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


@pytest.mark.xfail(
    strict=True,
    raises=tomllib.TOMLDecodeError,
    reason="an extra_config key that the generator also writes itself (auth, webServer, "
    "transport) is emitted a second time and TOML refuses the duplicate — the schema "
    "accepts the key, so the generated frps.toml simply does not parse",
)
def test_extra_config_may_collide_with_the_generators_own_keys():
    """extra_config lets an operator add frps.toml fields verbatim.

    _check_extra_config validates the key as a TOML bare key and the value as a
    scalar, but knows nothing about the lines config_generator writes itself. "auth"
    is one of them (auth.method / auth.token), so the file ends up defining `auth`
    twice: once as a table, once as a string. Availability, not injection — but the
    server then ships a config frps cannot read.
    """
    accepted = FrpServerConfigCreate(
        name="frps",
        server_addr="frps.example.test",
        auth_token="0123456789abcdef",
        extra_config={"auth": "hijack"},
    )
    assert accepted.extra_config == {"auth": "hijack"}  # the schema let it through

    toml = generate_frps_toml(_config(extra_config=json.dumps(accepted.extra_config)))
    tomllib.loads(toml)  # raises TOMLDecodeError -> the xfail


def test_allow_users_is_only_safe_because_usernames_are_validated():
    """allowUsers decides who may open an STCP tunnel — and the generator writes it
    without escaping.

    Nothing in the FRP layer stops a name from closing that quote; what stops it is
    _USERNAME_PATTERN in the users schema, two modules away. This test states that
    dependency out loud, so loosening the pattern (an e-mail login, a display name)
    fails here instead of quietly growing a tunnel's allow-list.
    """
    forged = 'mallory", "admin'
    with pytest.raises(ValidationError):
        UserCreate(username=forged, password="correct horse battery")

    # ...and this is what it would do if it ever got through:
    tunnel = _tunnel(name="t", secret_key="0123456789abcdef")
    parsed = tomllib.loads(generate_frpc_toml(_config(), [tunnel], "u", [forged]))
    assert parsed["proxies"][0]["allowUsers"] == ["mallory", "admin"], (
        "one name became two — the generator interpolates allowUsers verbatim"
    )


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
