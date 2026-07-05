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


def test_root_passphrase_from_env(monkeypatch):
    monkeypatch.delenv("CA_ROOT_PASSPHRASE_FILE", raising=False)
    monkeypatch.setenv("CA_ROOT_PASSPHRASE", "env-secret")
    assert config.root_passphrase() == b"env-secret"


def test_root_passphrase_file_preferred(monkeypatch, tmp_path):
    # 3.47: the _FILE variant (a Docker file secret) wins over the env var, which
    # leaks via docker inspect / /proc/<pid>/environ.
    secret = tmp_path / "pass"
    secret.write_bytes(b"file-secret\n")
    monkeypatch.setenv("CA_ROOT_PASSPHRASE_FILE", str(secret))
    monkeypatch.setenv("CA_ROOT_PASSPHRASE", "env-secret")
    assert config.root_passphrase() == b"file-secret"  # trailing whitespace stripped


def test_root_passphrase_none_when_unset(monkeypatch):
    monkeypatch.delenv("CA_ROOT_PASSPHRASE_FILE", raising=False)
    monkeypatch.delenv("CA_ROOT_PASSPHRASE", raising=False)
    assert config.root_passphrase() is None


def test_root_passphrase_empty_file_is_none(monkeypatch, tmp_path):
    # A whitespace-only secret file strips to nothing -> None (not b"").
    empty = tmp_path / "empty"
    empty.write_bytes(b"\n")
    monkeypatch.setenv("CA_ROOT_PASSPHRASE_FILE", str(empty))
    monkeypatch.delenv("CA_ROOT_PASSPHRASE", raising=False)
    assert config.root_passphrase() is None
