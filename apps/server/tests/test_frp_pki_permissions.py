# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Restrictive file permissions of the FRP PKI private keys (0600) and the PKI dir (0700).

Reproduces the finding 'FRP PKI keys world-readable': before the fix
_write_key wrote the keys with write_bytes() (umask-dependent -> 0644/0664).
These tests assert 0600 and fail without the fix.
"""

import os
import stat

from app.modules.frp import pki


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_pki_keys_written_owner_only(tmp_path, monkeypatch):
    pki_dir = tmp_path / "pki"
    monkeypatch.setattr(pki, "PKI_DIR", pki_dir)
    monkeypatch.setattr(pki, "PUBLISHED_PKI_DIR", tmp_path / "published")
    # Deliberately loose umask -> proves the umask robustness of the fix.
    old_umask = os.umask(0o022)
    try:
        pki.generate_ca()
        pki.generate_server_cert("frps.example.com")
        pki.generate_client_cert("k01-lnx1")
    finally:
        os.umask(old_umask)

    for key_name in ("ca.key", "frps.key", "k01-lnx1.key"):
        assert _mode(pki_dir / key_name) == 0o600, f"{key_name} ist nicht 0600"
    assert _mode(pki_dir) == 0o700
    # Certificates must stay readable (frps/frpc read them).
    assert _mode(pki_dir / "ca.crt") & 0o044, "ca.crt sollte lesbar bleiben"


def test_pki_dir_tightens_existing_lax_keys(tmp_path, monkeypatch):
    pki_dir = tmp_path / "pki"
    monkeypatch.setattr(pki, "PKI_DIR", pki_dir)
    monkeypatch.setattr(pki, "PUBLISHED_PKI_DIR", tmp_path / "published")
    pki.generate_ca()
    # Simulate an old, world-readable deployment.
    (pki_dir / "ca.key").chmod(0o644)
    pki_dir.chmod(0o755)
    # Every PKI access enforces the permissions idempotently.
    pki.get_pki_status()
    assert _mode(pki_dir / "ca.key") == 0o600
    assert _mode(pki_dir) == 0o700
