# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hermetic tests for scripts/tests/e2e_api.py: _call is replaced, nothing touches the network."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "e2e_api",
    pathlib.Path(__file__).resolve().parents[2] / "tests" / "e2e_api.py",
)
assert _SPEC and _SPEC.loader
e2e_api = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(e2e_api)

TUNNELS = [
    {"label": "ssh-a", "name": "srv · ssh-a (FRP)", "visitorPort": 7001},
    {"name": "legacy", "visitorPort": 7002},
    {"label": "web-b", "name": "srv · web-b (FRP)", "visitorPort": None},
]


@pytest.fixture
def visitor_port(monkeypatch, capsys):
    monkeypatch.setattr(e2e_api, "_call", lambda base, token, method, path, body=None: TUNNELS)

    def run(name: str) -> str:
        e2e_api.main(["https://gw", "tok", "visitor-port", name])
        return capsys.readouterr().out.strip()

    return run


def test_visitor_port_finds_the_tunnel_by_its_label(visitor_port):
    assert visitor_port("ssh-a") == "7001"


def test_visitor_port_falls_back_to_name_for_a_tunnel_without_label(visitor_port):
    assert visitor_port("legacy") == "7002"


def test_visitor_port_is_empty_for_a_tunnel_without_visitor_port(visitor_port):
    assert visitor_port("web-b") == ""


def test_visitor_port_is_empty_for_an_unknown_name(visitor_port):
    # The display name is not the label: only the name the tunnel was created with matches.
    assert visitor_port("srv · ssh-a (FRP)") == ""
    assert visitor_port("nope") == ""
