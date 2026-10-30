# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""pinned_client reads the environment's proxies with httpx's private
get_environment_proxies. The oracle here is a plain httpx.Client in the same
environment: where it goes to the proxy, pinned_client goes to the proxy; where it
connects to the host itself, pinned_client connects to the address the guard checked.
A change of httpx's proxy rules (monitoring pins httpx apart from the server) turns
this red instead of silently moving a request past the pin."""

import itertools
import socket
import ssl

import httpx
import pytest

import app.core.ssrf as ssrf_mod
from app.core.ssrf import check_target, pinned_client

_V4 = "93.184.216.34"
_PROXY = "http://192.0.2.10:3128"
_PROXY_CONNECTION = ("192.0.2.10", 3128)
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


@pytest.fixture(autouse=True)
def _no_proxy_from_the_shell(monkeypatch):
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def _connected(client: httpx.Client, url: str, connections: list[tuple]) -> list[tuple]:
    connections.clear()
    with client, pytest.raises(httpx.ConnectError):
        client.get(url, timeout=5)
    return list(connections)


def _port(url: str) -> int:
    parsed = httpx.URL(url)
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def test_with_a_proxy_httpx_picks_the_path_and_the_direct_one_is_pinned(monkeypatch):
    answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_V4, 0))]
    monkeypatch.setattr(ssrf_mod, "_resolve", lambda _host, _timeout: answer)
    connections: list[tuple] = []

    def _connect(address, *args, **kwargs):
        connections.append(address)
        raise ConnectionRefusedError("refused by the test")

    monkeypatch.setattr(socket, "create_connection", _connect)
    # One SSL context for every client: one each makes this test take seconds, and the
    # route does not depend on it.
    tls = ssl.create_default_context()
    proxy_envs = [("HTTP_PROXY",), ("HTTPS_PROXY",), ("ALL_PROXY",), ("HTTP_PROXY", "HTTPS_PROXY")]
    no_proxies = [
        None,
        "*",
        "pinned.example",
        ".example",
        ".pinned.example",
        "example",
        "pinned.example:8080",
        "http://pinned.example",
        "other.example",
        "other.example, *",
    ]
    urls = [
        "http://pinned.example/x",
        "http://pinned.example:8080/x",
        "https://pinned.example/x",
        "https://sub.pinned.example/x",
    ]
    outcomes = {"proxy": 0, "direct": 0}
    differing = []

    for names, no_proxy, url in itertools.product(proxy_envs, no_proxies, urls):
        env = dict.fromkeys(names, _PROXY)
        if no_proxy is not None:
            env["NO_PROXY"] = no_proxy
        with monkeypatch.context() as scoped:
            for name, value in env.items():
                scoped.setenv(name, value)
            plain = _connected(httpx.Client(verify=tls), url, connections)
            pinned = _connected(pinned_client(url, check_target(url), verify=tls), url, connections)
        if plain == [_PROXY_CONNECTION]:
            outcomes["proxy"] += 1
            expected = plain
        else:
            assert plain == [(httpx.URL(url).host, _port(url))], (env, url)
            outcomes["direct"] += 1
            expected = [(_V4, _port(url))]
        if pinned != expected:
            differing.append((env, url, pinned))

    assert differing == []
    assert outcomes["proxy"] > 0
    assert outcomes["direct"] > 0
