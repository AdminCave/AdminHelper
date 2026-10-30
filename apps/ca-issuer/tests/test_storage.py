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
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

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

    with pytest.raises(RuntimeError, match=r"'tunnel'.*tunnel\.crt.*expired") as exc:
        storage.ensure_hierarchy(tmp_path, None)
    assert "app.cli rotate-intermediates" in str(exc.value)
    assert "NTP" not in str(exc.value)


def test_a_not_yet_valid_intermediate_aborts_the_boot(monkeypatch, tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    _reissue(monkeypatch, tmp_path, "tunnel", shift_days=10)

    with pytest.raises(RuntimeError, match=r"'tunnel'.*tunnel\.crt.*not yet valid") as exc:
        storage.ensure_hierarchy(tmp_path, None)
    # Valid from its issuing: the clock is behind; a rotation refuses to run under it.
    assert "NTP" in str(exc.value)
    assert "app.cli rotate-intermediates" not in str(exc.value)


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


# The current intermediate passes the same check as a retired one, and a
# file the boot cannot read stops it with the file and the scope.


def test_another_scopes_intermediate_as_the_current_one_aborts_the_boot(tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    # Cert, key and chain of tunnel under the name of access: signature, key and chain match.
    for suffix in (".crt", ".key", "-chain.pem"):
        (tmp_path / f"access{suffix}").write_bytes((tmp_path / f"tunnel{suffix}").read_bytes())

    with pytest.raises(RuntimeError, match=r"'access'.*access\.crt.*CN"):
        storage.ensure_hierarchy(tmp_path, None)


def test_a_current_intermediate_that_may_sign_cas_aborts_the_boot(tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    root_cert, root_key = _root(tmp_path)
    now = pki._now()
    key = pki.generate_key()
    cert = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, "AdminHelper Access Intermediate"),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AdminHelper"),
                ]
            )
        )
        .issuer_name(root_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=100))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    (tmp_path / "access.crt").write_bytes(pki.cert_to_pem(cert))
    (tmp_path / "access.key").write_bytes(pki.key_to_pem(key))
    (tmp_path / "access-chain.pem").write_bytes(pki.chain_pem(cert, root_cert))

    with pytest.raises(RuntimeError, match=r"'access'.*access\.crt.*path_length"):
        storage.ensure_hierarchy(tmp_path, None)


@pytest.mark.parametrize(
    ("name", "pattern"),
    [
        ("root.crt", r"root\.crt.*not a PEM certificate"),
        ("internal.crt", r"'internal'.*internal\.crt.*not a PEM certificate"),
        ("internal.key", r"'internal'.*internal\.key.*not a PEM EC private key"),
    ],
)
def test_an_unreadable_hierarchy_file_aborts_the_boot_naming_it(tmp_path, name, pattern):
    storage.ensure_hierarchy(tmp_path, b"pw")
    (tmp_path / name).write_bytes(b"not a pem\n")

    with pytest.raises(RuntimeError, match=pattern) as exc:
        storage.ensure_hierarchy(tmp_path, None)
    assert str(exc.value).startswith("PKI hierarchy invalid")


def test_an_intermediate_key_of_another_type_aborts_the_boot_naming_it(tmp_path):
    from cryptography.hazmat.primitives.asymmetric import ed25519

    storage.ensure_hierarchy(tmp_path, b"pw")
    other = ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (tmp_path / "tunnel.key").write_bytes(other)

    with pytest.raises(RuntimeError, match=r"'tunnel'.*tunnel\.key.*not a PEM EC private key"):
        storage.ensure_hierarchy(tmp_path, None)


def test_an_encrypted_intermediate_key_aborts_the_boot_naming_it(tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    key = pki.key_from_pem((tmp_path / "access.key").read_bytes())
    (tmp_path / "access.key").write_bytes(pki.key_to_pem(key, passphrase=b"other"))

    with pytest.raises(RuntimeError, match=r"'access'.*access\.key.*not a PEM EC private key"):
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
    assert "app.cli rotate-intermediates" in warnings[0]


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
    # The command renews the intermediates under the root, never the root itself.
    assert "app.cli rotate-intermediates" not in root_warnings[0]
    assert all("app.cli rotate-intermediates" in w for w in warnings if w not in root_warnings)


def test_a_fresh_hierarchy_does_not_warn(tmp_path, caplog):
    storage.ensure_hierarchy(tmp_path, b"pw")
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="ca-issuer.storage")

    storage.ensure_hierarchy(tmp_path, None)

    assert _storage_warnings(caplog) == []


# R-0667: <scope>-retired.pem adds the scope's earlier intermediates (certificates only)
# as Intermediate.retired, so leaves they signed stay verifiable after a rotation.


def _minted(monkeypatch, pki_dir, scope: str, shift_days: float):
    """An intermediate certificate of `scope` from the hierarchy's root, minted
    `shift_days` from now on the PKI clock — what a retired file holds (no key)."""
    root_cert, root_key = _root(pki_dir)
    then = pki._now() + datetime.timedelta(days=shift_days)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: then)
        cert, _ = pki.build_intermediate_ca(scope, root_cert, root_key)
    return cert


def _current(pki_dir, scope: str):
    return pki.cert_from_pem((pki_dir / f"{scope}.crt").read_bytes())


def test_without_a_retired_file_no_scope_has_retired_intermediates(tmp_path):
    first = storage.ensure_hierarchy(tmp_path, b"pw")
    again = storage.ensure_hierarchy(tmp_path, None)

    for inter in (first, again):
        assert {scope: inter[scope].retired for scope in pki.SCOPES} == {
            scope: () for scope in pki.SCOPES
        }


def test_a_retired_file_adds_its_valid_intermediates_and_skips_expired_ones(
    monkeypatch, tmp_path, caplog
):
    # The first generation has expired; a second one, minted 10 days ago, is still valid.
    _booted(monkeypatch, tmp_path, days_ago=pki.VALIDITY_DAYS_INTERMEDIATE + 30)
    expired = _current(tmp_path, "access")
    valid = _minted(monkeypatch, tmp_path, "access", shift_days=-10)
    for scope in pki.SCOPES:
        _reissue(monkeypatch, tmp_path, scope)
    (tmp_path / "access-retired.pem").write_bytes(pki.chain_pem(expired, valid))
    caplog.clear()
    caplog.set_level(logging.INFO, logger="ca-issuer.storage")

    inter = storage.ensure_hierarchy(tmp_path, None)

    assert inter["access"].retired == (valid,)
    assert inter["tunnel"].retired == () and inter["internal"].retired == ()
    skipped = [
        r.getMessage()
        for r in caplog.records
        if r.name == "ca-issuer.storage"
        and r.levelno == logging.INFO
        and "retired" in r.getMessage()
    ]
    assert len(skipped) == 1, skipped
    assert pki.read_identity(expired)[0] in skipped[0]
    assert expired.not_valid_after_utc.isoformat() in skipped[0]


def _skip_warning(caplog, scope: str, cert) -> str:
    """The one storage WARNING, which skips `cert` from <scope>-retired.pem: it names the
    file, the scope and the CN; the caller checks the reason."""
    warnings = _storage_warnings(caplog)
    assert len(warnings) == 1, warnings
    assert f"{scope}-retired.pem" in warnings[0] and f"'{scope}'" in warnings[0]
    assert repr(pki.read_identity(cert)[0]) in warnings[0]
    return warnings[0]


def test_the_root_in_a_retired_file_is_skipped_with_a_warning(tmp_path, caplog):
    storage.ensure_hierarchy(tmp_path, b"pw")
    root, _ = _root(tmp_path)
    # Self-signed: the root passes a check of its signature against itself.
    (tmp_path / "access-retired.pem").write_bytes(pki.cert_to_pem(root))
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="ca-issuer.storage")

    inter = storage.ensure_hierarchy(tmp_path, None)

    assert inter["access"].retired == ()
    assert "CN" in _skip_warning(caplog, "access", root)


def test_another_scopes_intermediate_in_a_retired_file_is_skipped_with_a_warning(
    monkeypatch, tmp_path, caplog
):
    _booted(monkeypatch, tmp_path, days_ago=30)
    tunnel = _minted(monkeypatch, tmp_path, "tunnel", shift_days=-10)
    (tmp_path / "access-retired.pem").write_bytes(pki.cert_to_pem(tunnel))
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="ca-issuer.storage")

    inter = storage.ensure_hierarchy(tmp_path, None)

    assert inter["access"].retired == () and inter["tunnel"].retired == ()
    assert "CN" in _skip_warning(caplog, "access", tunnel)


def test_a_ca_that_may_sign_cas_in_a_retired_file_is_skipped_with_a_warning(
    monkeypatch, tmp_path, caplog
):
    _booted(monkeypatch, tmp_path, days_ago=30)
    root_cert, root_key = _root(tmp_path)
    now = pki._now()
    # The scope's CN and signed by the root, but path_length 1 instead of 0.
    cert = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, "AdminHelper Access Intermediate"),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AdminHelper"),
                ]
            )
        )
        .issuer_name(root_cert.subject)
        .public_key(pki.generate_key().public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=10))
        .not_valid_after(now + datetime.timedelta(days=100))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    (tmp_path / "access-retired.pem").write_bytes(pki.cert_to_pem(cert))
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="ca-issuer.storage")

    inter = storage.ensure_hierarchy(tmp_path, None)

    assert inter["access"].retired == ()
    assert "path_length" in _skip_warning(caplog, "access", cert)


def test_a_retired_intermediate_from_a_foreign_root_is_skipped_with_a_warning(
    monkeypatch, tmp_path, caplog
):
    _booted(monkeypatch, tmp_path, days_ago=30)
    valid = _minted(monkeypatch, tmp_path, "tunnel", shift_days=-10)
    _reissue(monkeypatch, tmp_path, "tunnel")
    # Same subject as our root, so only the signature tells them apart.
    foreign_root, foreign_key = pki.build_root_ca()
    foreign, _ = pki.build_intermediate_ca("tunnel", foreign_root, foreign_key)
    (tmp_path / "tunnel-retired.pem").write_bytes(pki.chain_pem(foreign, valid))
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="ca-issuer.storage")

    inter = storage.ensure_hierarchy(tmp_path, None)

    assert inter["tunnel"].retired == (valid,)
    assert "not signed by root" in _skip_warning(caplog, "tunnel", foreign)


# A signature algorithm cryptography does not know, swapped in at both places it is named
# (the TBS signature field and the outer one) for an OID of the same length.
_ECDSA_SHA256_OID = bytes.fromhex("06082a8648ce3d040302")  # 1.2.840.10045.4.3.2
_UNKNOWN_SIGNATURE_OID = bytes.fromhex("06082a8648ce3d04030f")  # 1.2.840.10045.4.3.15


def test_a_retired_intermediate_with_an_unknown_signature_algorithm_is_skipped_with_a_warning(
    monkeypatch, tmp_path, caplog
):
    _booted(monkeypatch, tmp_path, days_ago=30)
    der = _minted(monkeypatch, tmp_path, "access", shift_days=-10).public_bytes(
        serialization.Encoding.DER
    )
    assert der.count(_ECDSA_SHA256_OID) == 2
    odd = x509.load_der_x509_certificate(der.replace(_ECDSA_SHA256_OID, _UNKNOWN_SIGNATURE_OID))
    (tmp_path / "access-retired.pem").write_bytes(pki.cert_to_pem(odd))
    caplog.clear()
    caplog.set_level(logging.WARNING, logger="ca-issuer.storage")

    inter = storage.ensure_hierarchy(tmp_path, None)

    assert inter["access"].retired == ()
    warning = _skip_warning(caplog, "access", odd)
    assert "not signed by root" in warning and "signature algorithm" in warning.lower()


def test_a_retired_intermediate_not_valid_yet_is_left_out_with_an_info_line(
    monkeypatch, tmp_path, caplog
):
    storage.ensure_hierarchy(tmp_path, b"pw")
    later = _minted(monkeypatch, tmp_path, "access", shift_days=10)
    (tmp_path / "access-retired.pem").write_bytes(pki.cert_to_pem(later))
    caplog.clear()
    caplog.set_level(logging.INFO, logger="ca-issuer.storage")

    assert storage.ensure_hierarchy(tmp_path, None)["access"].retired == ()
    assert _storage_warnings(caplog) == []
    infos = [
        r.getMessage()
        for r in caplog.records
        if r.name == "ca-issuer.storage" and r.levelno == logging.INFO
    ]
    assert any("access-retired.pem" in m and "not yet valid" in m for m in infos), infos


def test_the_current_intermediate_in_the_retired_file_is_not_retired(monkeypatch, tmp_path):
    _booted(monkeypatch, tmp_path, days_ago=30)
    earlier = _current(tmp_path, "internal")
    _reissue(monkeypatch, tmp_path, "internal")
    (tmp_path / "internal-retired.pem").write_bytes(
        (tmp_path / "internal.crt").read_bytes() + pki.cert_to_pem(earlier)
    )

    assert storage.ensure_hierarchy(tmp_path, None)["internal"].retired == (earlier,)


def test_retired_intermediates_come_newest_first_and_once(monkeypatch, tmp_path):
    _booted(monkeypatch, tmp_path, days_ago=60)
    oldest = _current(tmp_path, "access")
    newer = _minted(monkeypatch, tmp_path, "access", shift_days=-30)
    _reissue(monkeypatch, tmp_path, "access")
    (tmp_path / "access-retired.pem").write_bytes(pki.chain_pem(oldest, newer, oldest))

    assert storage.ensure_hierarchy(tmp_path, None)["access"].retired == (newer, oldest)


def test_an_empty_retired_file_means_none(tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    (tmp_path / "access-retired.pem").write_bytes(b"\n")

    assert storage.ensure_hierarchy(tmp_path, None)["access"].retired == ()


def test_a_retired_file_without_a_certificate_aborts_the_boot(tmp_path):
    storage.ensure_hierarchy(tmp_path, b"pw")
    (tmp_path / "access-retired.pem").write_bytes(b"not a certificate\n")

    with pytest.raises(RuntimeError, match=r"'access'.*access-retired\.pem"):
        storage.ensure_hierarchy(tmp_path, None)
