# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The host key in every proxy of a frpc.toml (proxy_key.py), which frps' policy plugin checks."""

import hashlib
import hmac
import json
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import config as core_config
from app.modules.frp.config_generator import generate_frpc_toml, generate_visitor_toml
from app.modules.frp.proxy_key import PROXY_KEY_META, proxy_key, proxy_key_hash

SERVER_A = "0f1e2d3c-4b5a-4968-8776-655443322110"
SERVER_B = "7a0e4d2c-1b3f-4a5e-8c6d-9e0f1a2b3c4d"
AGENT_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "agent"
    / "internal"
    / "frpc"
    / "testdata"
    / "server_frpc.toml"
)


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(core_config, "SECRET_KEY", "secret-key-placeholder")
    return "secret-key-placeholder"


def _config():
    return SimpleNamespace(
        server_addr="frps.example.net",
        bind_port=7000,
        auth_token="secret-token",
        vhost_https_port=None,
        subdomain_host=None,
        max_ports_per_client=None,
        dashboard_port=None,
        dashboard_user=None,
        dashboard_password=None,
        extra_config=None,
    )


def _tunnel(**over):
    base = dict(
        id="t-ssh",
        name="ssh",
        tunnel_type="stcp",
        protocol="ssh",
        local_ip="127.0.0.1",
        local_port=22,
        secret_key="tunnel-secret",
        custom_domains=None,
        visitor_port=6001,
        enabled=True,
        extra_config=None,
        server_id=SERVER_A,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _https(**over):
    return _tunnel(
        **{
            "id": "t-web",
            "name": "web",
            "tunnel_type": "https",
            "protocol": "web",
            "local_port": 443,
            "secret_key": None,
            "custom_domains": "web.example",
            "visitor_port": None,
            **over,
        }
    )


def test_the_key_is_the_documented_derivation(secret):
    # docs/features/arch-frps-identity.md: K = HMAC(SECRET_KEY, label), key = HMAC(K, "frp-proxy-v1:" + id).
    k = hmac.new(secret.encode(), b"adminhelper/frp-proxy-key", hashlib.sha256).digest()
    want = hmac.new(k, f"frp-proxy-v1:{SERVER_A}".encode(), hashlib.sha256).hexdigest()
    assert proxy_key(SERVER_A, 0) == want
    assert re.fullmatch(r"[0-9a-f]{64}", want)


def test_a_later_generation_appends_its_number_to_the_message(secret):
    # Generation 0 keeps the message above, so the migration changed no host's key (R-1316).
    k = hmac.new(secret.encode(), b"adminhelper/frp-proxy-key", hashlib.sha256).digest()
    want = hmac.new(k, f"frp-proxy-v1:{SERVER_A}:2".encode(), hashlib.sha256).hexdigest()
    assert proxy_key(SERVER_A, 2) == want
    assert len({proxy_key(SERVER_A, n) for n in range(4)}) == 4


def test_a_generation_changes_the_key_of_its_host_alone(secret):
    assert proxy_key(SERVER_B, 0) == proxy_key(SERVER_B, 0)
    assert proxy_key(SERVER_A, 1) not in {proxy_key(SERVER_A, 0), proxy_key(SERVER_B, 1)}
    assert (
        proxy_key_hash(SERVER_A, 1) == hashlib.sha256(proxy_key(SERVER_A, 1).encode()).hexdigest()
    )
    assert proxy_key_hash(SERVER_A, 1) != proxy_key_hash(SERVER_A, 0)


def test_every_proxy_carries_the_key_of_the_generation_it_was_written_with(secret):
    tunnels = [_tunnel(), _https()]
    text = generate_frpc_toml(_config(), tunnels, SERVER_A, key_generation=5)
    proxies = tomllib.loads(text)["proxies"]
    assert {p["metadatas"][PROXY_KEY_META] for p in proxies} == {proxy_key(SERVER_A, 5)}
    assert proxy_key(SERVER_A, 0) not in text


def test_the_agent_fixture_carries_the_key_of_its_server(secret):
    # The same derivation the agent's fixture was written with (test_config_generator).
    text = AGENT_FIXTURE.read_bytes().decode("utf-8")
    proxies = tomllib.loads(text)["proxies"]
    assert proxies
    assert {p["metadatas"][PROXY_KEY_META] for p in proxies} == {proxy_key(SERVER_A, 0)}


def test_the_key_is_stable_and_differs_per_server(secret):
    assert proxy_key(SERVER_A, 0) == proxy_key(SERVER_A, 0)
    assert proxy_key(SERVER_A, 0) != proxy_key(SERVER_B, 0)


def test_the_key_hangs_on_secret_key(monkeypatch):
    monkeypatch.setattr(core_config, "SECRET_KEY", "one-secret")
    first = proxy_key(SERVER_A, 0)
    monkeypatch.setattr(core_config, "SECRET_KEY", "another-secret")
    assert proxy_key(SERVER_A, 0) != first


def test_the_policy_hash_is_the_sha256_of_the_key_text(secret):
    key = proxy_key(SERVER_A, 0)
    assert proxy_key_hash(SERVER_A, 0) == hashlib.sha256(key.encode()).hexdigest()
    assert proxy_key_hash(SERVER_A, 0) != key


def test_every_proxy_carries_the_key_of_its_host(secret):
    tunnels = [_tunnel(), _https(), _tunnel(id="t-rdp", name="rdp", local_port=3389)]
    proxies = tomllib.loads(generate_frpc_toml(_config(), tunnels, SERVER_A, key_generation=0))[
        "proxies"
    ]
    assert len(proxies) == 3
    for proxy in proxies:
        assert proxy["metadatas"] == {PROXY_KEY_META: proxy_key(SERVER_A, 0)}, proxy["name"]


def test_another_host_gets_its_own_key(secret):
    text = generate_frpc_toml(_config(), [_tunnel(server_id=SERVER_B)], SERVER_B, key_generation=0)
    assert proxy_key(SERVER_B, 0) in text
    assert proxy_key(SERVER_A, 0) not in text


def test_without_an_active_tunnel_no_key_is_written(secret):
    for tunnels in ([], [_tunnel(enabled=False)]):
        text = generate_frpc_toml(_config(), tunnels, SERVER_A, key_generation=0)
        assert PROXY_KEY_META not in text
        assert proxy_key(SERVER_A, 0) not in text


def test_the_visitor_config_carries_no_host_key(secret):
    text = generate_visitor_toml(_config(), [_tunnel()])
    assert PROXY_KEY_META not in text
    assert proxy_key(SERVER_A, 0) not in text


@pytest.mark.parametrize("key", ["metadatas.ahProxyKey", "Metadatas.AHPROXYKEY", "metadatas"])
def test_a_stored_row_that_sets_the_key_is_left_out(secret, key):
    # The schema refuses the key (test_frp_input_hardening); a row stored before keeps it and
    # must neither replace the host's key nor break the TOML of the other tunnels.
    forged = _https(id="t-forged", extra_config=json.dumps({key: "forged"}))
    proxies = tomllib.loads(
        generate_frpc_toml(_config(), [_tunnel(), forged], SERVER_A, key_generation=0)
    )["proxies"]
    assert [p["name"] for p in proxies] == ["t-ssh"]
    assert proxies[0]["metadatas"] == {PROXY_KEY_META: proxy_key(SERVER_A, 0)}


def test_another_metadatas_field_stays_beside_the_key(secret):
    tunnel = _tunnel(extra_config=json.dumps({"metadatas.owner": "ops"}))
    proxy = tomllib.loads(generate_frpc_toml(_config(), [tunnel], SERVER_A, key_generation=0))[
        "proxies"
    ][0]
    assert proxy["metadatas"] == {PROXY_KEY_META: proxy_key(SERVER_A, 0), "owner": "ops"}
