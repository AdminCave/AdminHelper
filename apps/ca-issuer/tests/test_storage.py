# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ca-issuer storage helpers: _write_private must fail closed if it cannot lock a
private signing key down to 0600, rather than logging a warning and continuing with a
group/world-readable key (3.49)."""

import pathlib

import pytest

from app import pki, storage


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


def test_hierarchy_encrypts_root_and_is_idempotent(tmp_path):
    # 6.2: ensure_hierarchy is the PKI's central persistence function. Assert first boot encrypts the
    # root key, locks the intermediate keys to 0600 and the PKI dir to 0700, and that a second boot
    # LOADS the existing hierarchy rather than regenerating it (a regression that regenerated would
    # silently invalidate every deployed certificate).
    inter1 = storage.ensure_hierarchy(tmp_path, b"pw")

    assert b"ENCRYPTED" in (tmp_path / "root.key.enc").read_bytes()
    assert (tmp_path / "tunnel.key").stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700

    # Second boot: no passphrase needed (the root stays cold), same intermediates loaded back.
    inter2 = storage.ensure_hierarchy(tmp_path, None)
    for scope in pki.SCOPES:
        assert pki.cert_to_pem(inter2[scope].cert) == pki.cert_to_pem(inter1[scope].cert)


def test_first_boot_without_passphrase_fails(tmp_path):
    # 6.2: a first boot without CA_ROOT_PASSPHRASE must raise, not silently write the root key in
    # cleartext (which would leave the suite green while the most valuable key sits unprotected).
    with pytest.raises(RuntimeError):
        storage.ensure_hierarchy(tmp_path / "fresh", None)
