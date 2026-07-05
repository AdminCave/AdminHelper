# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ca-issuer storage helpers: _write_private must fail closed if it cannot lock a
private signing key down to 0600, rather than logging a warning and continuing with a
group/world-readable key (3.49)."""

import pathlib

import pytest

from app import storage


def test_write_private_fails_closed_on_chmod_error(monkeypatch, tmp_path):
    def boom(self, mode):
        raise OSError("read-only fs")

    monkeypatch.setattr(pathlib.Path, "chmod", boom)
    with pytest.raises(RuntimeError, match="0600"):
        storage._write_private(tmp_path / "k.key", b"secret-signing-key")


def test_write_private_writes_key_at_0600(tmp_path):
    p = tmp_path / "k.key"
    storage._write_private(p, b"secret")
    assert p.read_bytes() == b"secret"
    assert (p.stat().st_mode & 0o777) == 0o600
