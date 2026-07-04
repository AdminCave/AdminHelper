# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Env-knob resolution — notably the frps/gateway EXTRA_SANS split (audit 2.8)."""

from app import config


def test_frps_extra_sans_uses_own_knob(monkeypatch):
    # frps can now carry SANs distinct from the gateway's.
    monkeypatch.setenv("EXTRA_SANS", "gw.example")
    monkeypatch.setenv("CA_FRPS_EXTRA_SANS", "frp.internal,10.0.0.9")
    assert config.frps_extra_sans() == "frp.internal,10.0.0.9"


def test_frps_extra_sans_falls_back_to_gateway(monkeypatch):
    # Unset -> mirror the gateway SANs (backwards compatible with the old alias).
    monkeypatch.delenv("CA_FRPS_EXTRA_SANS", raising=False)
    monkeypatch.setenv("EXTRA_SANS", "gw.example")
    assert config.frps_extra_sans() == "gw.example"
    assert config.frps_extra_sans() == config.gateway_extra_sans()
