# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rotation of the scoped intermediates (R-0667): new intermediates under the same root,
the replaced ones kept as retired and still able to verify their leaves, and nothing
changed when the rotation stops before writing."""

import datetime
import errno
import fcntl
import hashlib
import os

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from app import pki, rotation, storage

PW = b"pw"


def _at(monkeypatch, days_ago: float, run):
    """Run `run` with the PKI clock `days_ago` days back."""
    then = pki._now() - datetime.timedelta(days=days_ago)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: then)
        return run()


def _booted(monkeypatch, pki_dir, days_ago: float) -> dict[str, storage.Intermediate]:
    return _at(monkeypatch, days_ago, lambda: storage.ensure_hierarchy(pki_dir, PW))


def _rotated(monkeypatch, pki_dir, days_ago: float) -> list[rotation.RotatedScope]:
    return _at(monkeypatch, days_ago, lambda: rotation.rotate_intermediates(pki_dir, PW))


def _snapshot(pki_dir) -> dict[str, str]:
    """sha256 of every file in pki_dir but the lock file, which the rotation leaves."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in pki_dir.iterdir()
        if p.name != rotation.LOCK_NAME
    }


def _public_key(cert: x509.Certificate) -> bytes:
    return cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _retired_file(pki_dir, scope: str) -> list[x509.Certificate]:
    data = (pki_dir / f"{scope}-retired.pem").read_bytes()
    return x509.load_pem_x509_certificates(data) if data.strip() else []


def _leaf(inter: storage.Intermediate) -> x509.Certificate:
    key = pki.generate_key()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agent-01")]))
        .sign(key, hashes.SHA256())
    )
    return pki.sign_leaf(csr, inter.cert, inter.key, pki.LeafSpec(lifetime_days=30))


def test_rotation_issues_new_intermediates_and_retires_the_old_ones(monkeypatch, tmp_path):
    now = pki._now()
    monkeypatch.setattr(pki, "_now", lambda: now)  # one date for the CN, even at midnight
    before = storage.ensure_hierarchy(tmp_path, PW)
    old_leaves = {scope: _leaf(before[scope]) for scope in pki.SCOPES}

    rotated = rotation.rotate_intermediates(tmp_path, PW)
    after = storage.ensure_hierarchy(tmp_path, None)

    assert [r.scope for r in rotated] == list(pki.SCOPES)
    for r in rotated:
        old, new = before[r.scope], after[r.scope]
        assert r.old == old.cert and r.new == new.cert
        assert _public_key(new.cert) != _public_key(old.cert)
        name = f"AdminHelper {r.scope.capitalize()} Intermediate {now:%Y-%m-%d}"
        assert pki.read_identity(new.cert)[0] == name
        assert new.retired == (old.cert,)
        # A leaf of the old intermediate verifies against the retired one only.
        old_leaves[r.scope].verify_directly_issued_by(new.retired[0])
        with pytest.raises(ValueError):
            old_leaves[r.scope].verify_directly_issued_by(new.cert)
        _leaf(new).verify_directly_issued_by(new.cert)


def test_a_new_intermediate_ends_no_later_than_the_root(monkeypatch, tmp_path):
    # The root has 100 days left; the first intermediates have expired by now.
    _booted(monkeypatch, tmp_path, days_ago=pki.VALIDITY_DAYS_ROOT - 100)
    root = pki.cert_from_pem((tmp_path / "root.crt").read_bytes())

    rotated = rotation.rotate_intermediates(tmp_path, PW)

    for r in rotated:
        assert r.new.not_valid_after_utc <= root.not_valid_after_utc
    assert set(storage.ensure_hierarchy(tmp_path, None)) == set(pki.SCOPES)


def test_a_wrong_passphrase_changes_nothing(tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match="wrong passphrase or unreadable root key"):
        rotation.rotate_intermediates(tmp_path, b"not-the-passphrase")

    assert _snapshot(tmp_path) == before  # also: no temporary file left


def test_a_root_certificate_of_another_root_changes_nothing(tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)
    foreign, _ = pki.build_root_ca()
    (tmp_path / "root.crt").write_bytes(pki.cert_to_pem(foreign))
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match=r"root\.key\.enc is not the private key"):
        rotation.rotate_intermediates(tmp_path, PW)

    assert _snapshot(tmp_path) == before


def test_an_expired_root_changes_nothing(monkeypatch, tmp_path):
    _booted(monkeypatch, tmp_path, days_ago=pki.VALIDITY_DAYS_ROOT + 1)
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match=r"root\.crt is not valid now"):
        rotation.rotate_intermediates(tmp_path, PW)

    assert _snapshot(tmp_path) == before


def test_a_retired_file_with_a_foreign_intermediate_changes_nothing(tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)
    foreign_root, foreign_key = pki.build_root_ca()
    cert, _ = pki.build_intermediate_ca("tunnel", foreign_root, foreign_key)
    (tmp_path / "tunnel-retired.pem").write_bytes(pki.cert_to_pem(cert))
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match=r"tunnel-retired\.pem.*not signed by root"):
        rotation.rotate_intermediates(tmp_path, PW)

    assert _snapshot(tmp_path) == before


def test_the_root_in_a_retired_file_changes_nothing(tmp_path):
    # The boot skips it with a WARNING; the rotation neither carries it on nor drops it.
    storage.ensure_hierarchy(tmp_path, PW)
    (tmp_path / "access-retired.pem").write_bytes((tmp_path / "root.crt").read_bytes())
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match=r"access-retired\.pem.*CN"):
        rotation.rotate_intermediates(tmp_path, PW)

    assert _snapshot(tmp_path) == before


def test_a_second_rotation_keeps_both_predecessors(monkeypatch, tmp_path):
    first = _booted(monkeypatch, tmp_path, days_ago=20)
    second = _rotated(monkeypatch, tmp_path, days_ago=10)

    third = rotation.rotate_intermediates(tmp_path, PW)

    inter = storage.ensure_hierarchy(tmp_path, None)
    for i, scope in enumerate(pki.SCOPES):
        assert inter[scope].cert == third[i].new
        assert inter[scope].retired == (second[i].new, first[scope].cert)
        assert _retired_file(tmp_path, scope) == [second[i].new, first[scope].cert]


def test_a_predecessor_that_expired_leaves_the_retired_file(monkeypatch, tmp_path):
    # The first generation ended 30 days ago; at the first rotation it had 10 days left.
    first = _booted(monkeypatch, tmp_path, days_ago=pki.VALIDITY_DAYS_INTERMEDIATE + 30)
    second = _rotated(monkeypatch, tmp_path, days_ago=40)
    for scope in pki.SCOPES:
        assert _retired_file(tmp_path, scope) == [first[scope].cert]

    rotation.rotate_intermediates(tmp_path, PW)

    for i, scope in enumerate(pki.SCOPES):
        assert _retired_file(tmp_path, scope) == [second[i].new]


def test_a_held_lock_stops_the_rotation(tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)
    fd = os.open(tmp_path / rotation.LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = _snapshot(tmp_path)

        with pytest.raises(rotation.RotationError, match="another rotation is running"):
            rotation.rotate_intermediates(tmp_path, PW)

        assert _snapshot(tmp_path) == before
    finally:
        os.close(fd)
    # Released, the same call runs.
    assert len(rotation.rotate_intermediates(tmp_path, PW)) == len(pki.SCOPES)


def test_an_interrupted_rotation_is_repaired_by_the_next_one(monkeypatch, tmp_path):
    original = storage.ensure_hierarchy(tmp_path, PW)
    real_replace = os.replace

    def replace(src, dst):
        if os.path.basename(dst) == "access.crt":
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        real_replace(src, dst)

    with monkeypatch.context() as m:
        m.setattr(os, "replace", replace)
        with pytest.raises(rotation.RotationError, match=r"access\.crt"):
            rotation.rotate_intermediates(tmp_path, PW)

    # access: new key, old certificate. The issuer does not start with that pair.
    assert pki.cert_from_pem((tmp_path / "access.crt").read_bytes()) == original["access"].cert
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    with pytest.raises(RuntimeError, match=r"'access'.*access\.key"):
        storage.ensure_hierarchy(tmp_path, None)

    rotation.rotate_intermediates(tmp_path, PW)

    inter = storage.ensure_hierarchy(tmp_path, None)
    assert original["access"].cert in inter["access"].retired
    for scope in pki.SCOPES:
        assert inter[scope].cert != original[scope].cert


def test_the_new_intermediate_keys_are_0600(tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)

    rotation.rotate_intermediates(tmp_path, PW)

    for scope in pki.SCOPES:
        assert (tmp_path / f"{scope}.key").stat().st_mode & 0o777 == 0o600


def test_an_expired_intermediate_is_replaced_but_not_retired(monkeypatch, tmp_path):
    # The case in which the issuer no longer starts (R-0666).
    first = _booted(monkeypatch, tmp_path, days_ago=pki.VALIDITY_DAYS_INTERMEDIATE + 30)
    with pytest.raises(RuntimeError, match="expired"):
        storage.ensure_hierarchy(tmp_path, None)

    rotated = rotation.rotate_intermediates(tmp_path, PW)

    inter = storage.ensure_hierarchy(tmp_path, None)
    for r in rotated:
        assert r.old == first[r.scope].cert
        assert inter[r.scope].cert == r.new
        assert inter[r.scope].retired == ()
        assert _retired_file(tmp_path, r.scope) == []


def test_another_scopes_intermediate_as_current_is_replaced_but_not_retired(tmp_path):
    # A restore with the scopes mixed up: access.crt holds tunnel's intermediate, signed by
    # the root and valid. Retired, it would be an entry the boot skips and the next
    # rotation stops at; the rotation replaces it, as it replaces any wrong <scope>.crt.
    tunnel = storage.ensure_hierarchy(tmp_path, PW)["tunnel"].cert
    (tmp_path / "access.crt").write_bytes(pki.cert_to_pem(tunnel))
    (tmp_path / "access-chain.pem").write_bytes((tmp_path / "tunnel-chain.pem").read_bytes())

    first = {r.scope: r for r in rotation.rotate_intermediates(tmp_path, PW)}

    assert first["access"].old == tunnel
    assert _retired_file(tmp_path, "access") == []
    assert _retired_file(tmp_path, "tunnel") == [tunnel]
    second = {r.scope: r for r in rotation.rotate_intermediates(tmp_path, PW)}
    assert second["access"].old == first["access"].new
    assert storage.ensure_hierarchy(tmp_path, None)["access"].retired == (first["access"].new,)


def test_a_current_intermediate_not_valid_yet_changes_nothing(monkeypatch, tmp_path):
    # access was issued ten days after the others; this clock is five days behind that.
    # Replaced under it, access would not be kept as retired.
    _booted(monkeypatch, tmp_path, days_ago=10)
    root = pki.cert_from_pem((tmp_path / "root.crt").read_bytes())
    root_key = pki.key_from_pem((tmp_path / "root.key.enc").read_bytes(), PW)
    cert, key = pki.build_intermediate_ca("access", root, root_key)
    (tmp_path / "access.crt").write_bytes(pki.cert_to_pem(cert))
    (tmp_path / "access.key").write_bytes(pki.key_to_pem(key))
    (tmp_path / "access-chain.pem").write_bytes(pki.chain_pem(cert, root))
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match=r"access\.crt") as exc:
        _rotated(monkeypatch, tmp_path, days_ago=5)

    message = str(exc.value)
    assert "AdminHelper Access Intermediate" in message
    assert cert.not_valid_before_utc.isoformat() in message
    assert "host clock" in message and "NTP" in message
    assert _snapshot(tmp_path) == before  # also: no temporary file left
