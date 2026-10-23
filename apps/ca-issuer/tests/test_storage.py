# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ca-issuer storage helpers: _write_private must fail closed if it cannot lock a
private signing key down to 0600, rather than logging a warning and continuing with a
group/world-readable key (3.49)."""

import datetime
import logging
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


# R-0666: ensure_hierarchy hands out only a hierarchy whose intermediates come from the
# root, are valid now and match their key and chain; one nearing its end is a WARNING.


def _booted(monkeypatch, pki_dir, days_ago: float) -> None:
    """First boot of a hierarchy, `days_ago` days back on the PKI clock."""
    then = pki._now() - datetime.timedelta(days=days_ago)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: then)
        storage.ensure_hierarchy(pki_dir, b"pw")


def _root(pki_dir):
    root_cert = pki.cert_from_pem((pki_dir / "root.crt").read_bytes())
    root_key = pki.key_from_pem((pki_dir / "root.key.enc").read_bytes(), passphrase=b"pw")
    return root_cert, root_key


def _reissue(monkeypatch, pki_dir, scope: str, shift_days: float = 0) -> None:
    """Replace `scope` by a consistent intermediate (cert, key, chain) from the same
    root, minted `shift_days` from now on the PKI clock (negative = in the past)."""
    root_cert, root_key = _root(pki_dir)
    then = pki._now() + datetime.timedelta(days=shift_days)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: then)
        cert, key = pki.build_intermediate_ca(scope, root_cert, root_key)
    (pki_dir / f"{scope}.crt").write_bytes(pki.cert_to_pem(cert))
    (pki_dir / f"{scope}.key").write_bytes(pki.key_to_pem(key))
    (pki_dir / f"{scope}-chain.pem").write_bytes(pki.chain_pem(cert, root_cert))


def _storage_warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "ca-issuer.storage" and r.levelno == logging.WARNING
    ]


def test_an_expired_intermediate_aborts_the_boot(monkeypatch, tmp_path):
    # A hierarchy older than an intermediate's life; only tunnel is still the original.
    _booted(monkeypatch, tmp_path, days_ago=pki.VALIDITY_DAYS_INTERMEDIATE + 30)
    _reissue(monkeypatch, tmp_path, "access")
    _reissue(monkeypatch, tmp_path, "internal")

    with pytest.raises(RuntimeError, match=r"'tunnel'.*tunnel\.crt.*expired"):
        storage.ensure_hierarchy(tmp_path, None)


def test_a_not_yet_valid_intermediate_aborts_the_boot(monkeypatch, tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    _reissue(monkeypatch, tmp_path, "tunnel", shift_days=10)

    with pytest.raises(RuntimeError, match=r"'tunnel'.*tunnel\.crt.*not yet valid"):
        storage.ensure_hierarchy(tmp_path, None)


def test_an_intermediate_from_a_foreign_root_aborts_the_boot(tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    root_cert, _ = _root(tmp_path)
    # Same subject as our root, so only the signature tells them apart; key and chain match.
    foreign_root, foreign_key = pki.build_root_ca()
    cert, key = pki.build_intermediate_ca("access", foreign_root, foreign_key)
    (tmp_path / "access.crt").write_bytes(pki.cert_to_pem(cert))
    (tmp_path / "access.key").write_bytes(pki.key_to_pem(key))
    (tmp_path / "access-chain.pem").write_bytes(pki.chain_pem(cert, root_cert))

    with pytest.raises(RuntimeError, match=r"'access'.*access\.crt.*not signed by root\.crt"):
        storage.ensure_hierarchy(tmp_path, None)


def test_a_key_that_does_not_match_its_intermediate_aborts_the_boot(tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    (tmp_path / "internal.key").write_bytes(pki.key_to_pem(pki.generate_key()))

    with pytest.raises(RuntimeError, match=r"'internal'.*internal\.key.*internal\.crt"):
        storage.ensure_hierarchy(tmp_path, None)


def test_a_chain_of_another_scope_aborts_the_boot(tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    (tmp_path / "tunnel-chain.pem").write_bytes((tmp_path / "access-chain.pem").read_bytes())

    with pytest.raises(RuntimeError, match=r"'tunnel'.*tunnel-chain\.pem"):
        storage.ensure_hierarchy(tmp_path, None)


def test_a_chain_with_other_line_endings_still_loads(tmp_path):
    # Compared parsed, not byte for byte: a restore that rewrote the line endings passes.
    storage.ensure_hierarchy(tmp_path, b"pw")
    chain = tmp_path / "tunnel-chain.pem"
    chain.write_bytes(chain.read_bytes().replace(b"\n", b"\r\n"))

    assert set(storage.ensure_hierarchy(tmp_path, None)) == set(pki.SCOPES)


def test_the_chain_handed_out_is_built_from_the_checked_certificates(tmp_path):
    # The file passes the parsed check with text around the two certificates; what the
    # issuer hands out (enroll responses, trust bundles) is the canonical chain, not the file.
    storage.ensure_hierarchy(tmp_path, b"pw")
    inter_pem = (tmp_path / "tunnel.crt").read_bytes()
    root_pem = (tmp_path / "root.crt").read_bytes()
    (tmp_path / "tunnel-chain.pem").write_bytes(
        b"# tunnel intermediate\n\n" + inter_pem + b"\n# root\n" + root_pem + b"\n\n"
    )

    tunnel = storage.ensure_hierarchy(tmp_path, None)["tunnel"]

    assert tunnel.chain == pki.chain_pem(tunnel.cert, pki.cert_from_pem(root_pem))


def test_an_expired_root_aborts_the_boot(monkeypatch, tmp_path):
    _booted(monkeypatch, tmp_path, days_ago=pki.VALIDITY_DAYS_ROOT + 1)

    with pytest.raises(RuntimeError, match=r"root\.crt.*expired"):
        storage.ensure_hierarchy(tmp_path, None)


def test_a_root_that_is_not_self_signed_aborts_the_boot(tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    (tmp_path / "root.crt").write_bytes((tmp_path / "tunnel.crt").read_bytes())

    with pytest.raises(RuntimeError, match=r"root\.crt.*not self-signed"):
        storage.ensure_hierarchy(tmp_path, None)


def test_an_intermediate_near_its_end_loads_with_one_warning(monkeypatch, tmp_path, caplog):
    _booted(monkeypatch, tmp_path, days_ago=pki.VALIDITY_DAYS_INTERMEDIATE - 30)
    _reissue(monkeypatch, tmp_path, "access")
    _reissue(monkeypatch, tmp_path, "internal")
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="ca-issuer.storage")

    inter = storage.ensure_hierarchy(tmp_path, None)

    warnings = _storage_warnings(caplog)
    assert len(warnings) == 1, warnings
    assert "'tunnel'" in warnings[0]
    assert inter["tunnel"].cert.not_valid_after_utc.isoformat() in warnings[0]


def test_a_root_near_its_end_warns_that_clients_must_enroll_again(monkeypatch, tmp_path, caplog):
    # Intermediates minted now end with the root (pki caps them), so all four warn.
    _booted(monkeypatch, tmp_path, days_ago=pki.VALIDITY_DAYS_ROOT - 30)
    for scope in pki.SCOPES:
        _reissue(monkeypatch, tmp_path, scope)
    root_cert, _ = _root(tmp_path)
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="ca-issuer.storage")

    storage.ensure_hierarchy(tmp_path, None)

    warnings = _storage_warnings(caplog)
    assert len(warnings) == 1 + len(pki.SCOPES), warnings
    root_warnings = [w for w in warnings if w.startswith("root ")]
    assert len(root_warnings) == 1, warnings
    assert root_cert.not_valid_after_utc.isoformat() in root_warnings[0]
    assert "enroll" in root_warnings[0]


def test_a_fresh_hierarchy_does_not_warn(tmp_path, caplog):
    storage.ensure_hierarchy(tmp_path, b"pw")
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="ca-issuer.storage")

    storage.ensure_hierarchy(tmp_path, None)

    assert _storage_warnings(caplog) == []
