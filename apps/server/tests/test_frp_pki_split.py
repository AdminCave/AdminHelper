# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Master/published PKI split (GHSA-rv39): the CA private key and client keys
must live in the server-private master dir and NEVER in the shared frp-config
volume that the internet-facing frps mounts. frps only ever sees ca.crt,
frps.crt and frps.key."""

import stat

from app.modules.frp import pki


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _patch_dirs(tmp_path, monkeypatch):
    master = tmp_path / "master"
    published = tmp_path / "published"
    monkeypatch.setattr(pki, "PKI_DIR", master)
    monkeypatch.setattr(pki, "PUBLISHED_PKI_DIR", published)
    return master, published


def test_published_dir_holds_only_frps_subset(tmp_path, monkeypatch):
    master, published = _patch_dirs(tmp_path, monkeypatch)

    pki.generate_ca()
    pki.generate_server_cert("frps.example.com")
    pki.generate_client_cert("k01-lnx1")

    # Master holds the secrets.
    assert (master / "ca.key").exists()
    assert (master / "k01-lnx1.key").exists()
    assert (master / "k01-lnx1.crt").exists()

    # Shared/published dir holds ONLY what frps needs.
    published_files = {f.name for f in published.iterdir() if f.is_file()}
    assert published_files == {"ca.crt", "frps.crt", "frps.key"}
    # The catastrophic leak: CA key / client key must not be in the shared volume.
    assert not (published / "ca.key").exists()
    assert not (published / "k01-lnx1.key").exists()
    assert not (published / "k01-lnx1.crt").exists()


def test_published_frps_key_is_restrictive(tmp_path, monkeypatch):
    _, published = _patch_dirs(tmp_path, monkeypatch)
    pki.generate_ca()
    pki.generate_server_cert("frps.example.com")
    assert _mode(published / "frps.key") == 0o600
    # Certs stay readable for frps.
    assert _mode(published / "ca.crt") & 0o044
    assert _mode(published / "frps.crt") & 0o044


def test_migration_moves_legacy_secrets_out_of_shared(tmp_path, monkeypatch):
    master, published = _patch_dirs(tmp_path, monkeypatch)

    # Simulate a pre-split deployment: the FULL PKI lives in the shared volume
    # (master empty). Generate everything straight into `published`.
    monkeypatch.setattr(pki, "PKI_DIR", published)
    pki.generate_ca()
    pki.generate_server_cert("frps.example.com")
    pki.generate_client_cert("k01-lnx1")
    ca_crt_before = (published / "ca.crt").read_bytes()
    assert (published / "ca.key").exists()  # the leak we are fixing
    assert (published / "k01-lnx1.key").exists()

    # Restore the split dirs and run the migration.
    monkeypatch.setattr(pki, "PKI_DIR", master)
    moved = pki.migrate_master_pki_out_of_shared()
    assert moved is True

    # Secrets now live in the master dir...
    assert (master / "ca.key").exists()
    assert (master / "k01-lnx1.key").exists()
    # ...and are gone from the internet-facing volume.
    assert not (published / "ca.key").exists()
    assert not (published / "k01-lnx1.key").exists()
    assert not (published / "k01-lnx1.crt").exists()
    # frps subset still present and the CA was preserved (not regenerated).
    assert {f.name for f in published.iterdir() if f.is_file()} == {
        "ca.crt", "frps.crt", "frps.key",
    }
    assert (master / "ca.crt").read_bytes() == ca_crt_before


def test_migration_is_idempotent_and_noop_without_legacy(tmp_path, monkeypatch):
    master, published = _patch_dirs(tmp_path, monkeypatch)
    # Clean split deployment: nothing to migrate.
    pki.generate_ca()
    pki.generate_server_cert("frps.example.com")
    assert pki.migrate_master_pki_out_of_shared() is False
    # Master still intact, published still the subset.
    assert (master / "ca.key").exists()
    assert {f.name for f in published.iterdir() if f.is_file()} == {
        "ca.crt", "frps.crt", "frps.key",
    }
