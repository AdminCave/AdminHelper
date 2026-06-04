# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Restriktive Dateirechte der FRP-PKI-Privatkeys (0600) und des PKI-Dirs (0700).

Reproduziert den Befund 'FRP-PKI-Keys world-readable': vor dem Fix schrieb
_write_key die Keys mit write_bytes() (umask-abhaengig -> 0644/0664). Diese
Tests asserten 0600 und schlagen ohne den Fix fehl.
"""

import os
import stat

from app.modules.frp import pki


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_pki_keys_written_owner_only(tmp_path, monkeypatch):
    pki_dir = tmp_path / "pki"
    monkeypatch.setattr(pki, "PKI_DIR", pki_dir)
    # Bewusst lockere umask -> beweist umask-Robustheit des Fixes.
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
    # Zertifikate muessen lesbar bleiben (frps/frpc lesen sie).
    assert _mode(pki_dir / "ca.crt") & 0o044, "ca.crt sollte lesbar bleiben"


def test_pki_dir_tightens_existing_lax_keys(tmp_path, monkeypatch):
    pki_dir = tmp_path / "pki"
    monkeypatch.setattr(pki, "PKI_DIR", pki_dir)
    pki.generate_ca()
    # Simuliere ein altes, world-readable Deployment.
    (pki_dir / "ca.key").chmod(0o644)
    pki_dir.chmod(0o755)
    # Jeder PKI-Zugriff zieht die Rechte idempotent nach.
    pki.get_pki_status()
    assert _mode(pki_dir / "ca.key") == 0o600
    assert _mode(pki_dir) == 0o700
