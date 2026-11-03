# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PKI engine: the two-tier hierarchy, leaf signing from CSRs, and key
serialization (incl. the encrypted cold root)."""

import datetime
import ipaddress

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

from app import pki


def _csr(common_name: str) -> tuple[x509.CertificateSigningRequest, ec.EllipticCurvePrivateKey]:
    """A CSR as a client would build it on-device (key never leaves the device)."""
    key = pki.generate_key()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(key, hashes.SHA256())
    )
    return csr, key


# --- Hierarchy ---------------------------------------------------------------


def test_root_is_ca_and_ecdsa_p256():
    root_cert, root_key = pki.build_root_ca()
    bc = root_cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is True
    assert isinstance(root_key.curve, ec.SECP256R1)
    # self-signed
    root_cert.verify_directly_issued_by(root_cert)
    # ~10 years
    span = root_cert.not_valid_after_utc - root_cert.not_valid_before_utc
    assert abs(span.days - pki.VALIDITY_DAYS_ROOT) <= 1


def test_intermediate_is_pathlen0_ca_signed_by_root():
    root_cert, root_key = pki.build_root_ca()
    inter_cert, _ = pki.build_intermediate_ca("tunnel", root_cert, root_key)
    bc = inter_cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is True
    assert bc.path_length == 0
    # chains to root
    inter_cert.verify_directly_issued_by(root_cert)


def test_unknown_scope_rejected():
    root_cert, root_key = pki.build_root_ca()
    with pytest.raises(ValueError):
        pki.build_intermediate_ca("bogus", root_cert, root_key)


# --- Leaf signing ------------------------------------------------------------


def test_agent_leaf_is_client_auth_only_and_chains():
    root_cert, root_key = pki.build_root_ca()
    inter_cert, inter_key = pki.build_intermediate_ca("tunnel", root_cert, root_key)
    csr, _ = _csr("agent-srv-01")

    leaf = pki.sign_leaf(
        csr,
        inter_cert,
        inter_key,
        pki.LeafSpec(lifetime_days=pki.LEAF_DAYS_NATIVE, client_auth=True, server_auth=False),
    )

    # not a CA
    bc = leaf.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is False
    # client-auth only
    eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.CLIENT_AUTH in eku
    assert ExtendedKeyUsageOID.SERVER_AUTH not in eku
    # subject preserved from CSR, key is the CSR's (never the issuer's)
    assert leaf.subject == csr.subject
    assert leaf.public_key().public_numbers() == csr.public_key().public_numbers()
    # full chain leaf -> intermediate -> root
    leaf.verify_directly_issued_by(inter_cert)
    inter_cert.verify_directly_issued_by(root_cert)
    # native lifetime
    span = leaf.not_valid_after_utc - leaf.not_valid_before_utc
    assert abs(span.days - pki.LEAF_DAYS_NATIVE) <= 1


def test_server_leaf_has_serverauth_and_san():
    root_cert, root_key = pki.build_root_ca()
    inter_cert, inter_key = pki.build_intermediate_ca("access", root_cert, root_key)
    csr, _ = _csr("localhost")

    leaf = pki.sign_leaf(
        csr,
        inter_cert,
        inter_key,
        pki.LeafSpec(
            lifetime_days=pki.LEAF_DAYS_BROWSER,
            server_auth=True,
            client_auth=False,
            dns_names=("localhost", "admin.example"),
            ip_addresses=("127.0.0.1",),
        ),
    )
    eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert "admin.example" in san.get_values_for_type(x509.DNSName)
    assert ipaddress.ip_address("127.0.0.1") in san.get_values_for_type(x509.IPAddress)


def test_leaf_rejects_tampered_csr():
    root_cert, root_key = pki.build_root_ca()
    inter_cert, inter_key = pki.build_intermediate_ca("access", root_cert, root_key)
    csr, _ = _csr("ok")
    # Re-encode the CSR with a flipped signature byte → is_signature_valid False.
    der = bytearray(csr.public_bytes(serialization.Encoding.DER))
    der[-1] ^= 0xFF
    tampered = x509.load_der_x509_csr(bytes(der))
    with pytest.raises(ValueError):
        pki.sign_leaf(tampered, inter_cert, inter_key, pki.LeafSpec(lifetime_days=30))


def test_leaf_requires_an_eku():
    root_cert, root_key = pki.build_root_ca()
    inter_cert, inter_key = pki.build_intermediate_ca("access", root_cert, root_key)
    csr, _ = _csr("ok")
    with pytest.raises(ValueError):
        pki.sign_leaf(
            csr,
            inter_cert,
            inter_key,
            pki.LeafSpec(lifetime_days=30, server_auth=False, client_auth=False),
        )


# --- No certificate outlives its issuer -------------------------------------


def _minted_at(monkeypatch, shift_days: float, build):
    """Run `build` with the PKI clock shifted by `shift_days` (negative = past),
    so what it mints is that much older or younger than the real clock."""
    then = pki._now() + datetime.timedelta(days=shift_days)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: then)
        return build()


def _intermediate_with_days_left(monkeypatch, days_left: float, scope: str = "tunnel"):
    """Root + intermediate of `scope`, minted in the past so the intermediate has
    `days_left` left on the real clock (negative = already expired)."""

    def build():
        root_cert, root_key = pki.build_root_ca()
        return pki.build_intermediate_ca(scope, root_cert, root_key)

    return _minted_at(monkeypatch, days_left - pki.VALIDITY_DAYS_INTERMEDIATE, build)


def test_leaf_is_cut_to_the_end_of_its_intermediate(monkeypatch):
    inter_cert, inter_key = _intermediate_with_days_left(monkeypatch, 5)
    csr, _ = _csr("agent-srv-01")

    leaf = pki.sign_leaf(
        csr, inter_cert, inter_key, pki.LeafSpec(lifetime_days=pki.LEAF_DAYS_NATIVE)
    )

    assert leaf.not_valid_after_utc == inter_cert.not_valid_after_utc
    leaf.verify_directly_issued_by(inter_cert)


def test_server_leaf_is_cut_to_the_end_of_its_intermediate(monkeypatch):
    inter_cert, inter_key = _intermediate_with_days_left(monkeypatch, 5, scope="access")

    leaf, _ = pki.build_server_leaf(
        inter_cert, inter_key, "gw.example", lifetime_days=pki.LEAF_DAYS_GATEWAY
    )

    assert leaf.not_valid_after_utc == inter_cert.not_valid_after_utc


def test_intermediate_is_cut_to_the_end_of_its_root(monkeypatch):
    root_cert, root_key = _minted_at(monkeypatch, 100 - pki.VALIDITY_DAYS_ROOT, pki.build_root_ca)

    inter_cert, _ = pki.build_intermediate_ca("tunnel", root_cert, root_key)

    assert inter_cert.not_valid_after_utc == root_cert.not_valid_after_utc
    inter_cert.verify_directly_issued_by(root_cert)


def test_expired_intermediate_does_not_sign(monkeypatch):
    inter_cert, inter_key = _intermediate_with_days_left(monkeypatch, -1)
    csr, _ = _csr("agent-srv-01")

    with pytest.raises(pki.IssuerNotValid, match=r"Tunnel Intermediate.*expired"):
        pki.sign_leaf(csr, inter_cert, inter_key, pki.LeafSpec(lifetime_days=30))


def test_expired_root_does_not_sign_an_intermediate(monkeypatch):
    root_cert, root_key = _minted_at(monkeypatch, -pki.VALIDITY_DAYS_ROOT - 1, pki.build_root_ca)

    with pytest.raises(pki.IssuerNotValid, match=r"Root CA.*expired"):
        pki.build_intermediate_ca("tunnel", root_cert, root_key)


def test_not_yet_valid_intermediate_does_not_sign(monkeypatch):
    def build():
        root_cert, root_key = pki.build_root_ca()
        return pki.build_intermediate_ca("access", root_cert, root_key)

    inter_cert, inter_key = _minted_at(monkeypatch, 10, build)
    csr, _ = _csr("agent-srv-01")

    with pytest.raises(pki.IssuerNotValid, match=r"Access Intermediate.*not yet valid"):
        pki.sign_leaf(csr, inter_cert, inter_key, pki.LeafSpec(lifetime_days=30))


def test_days_left_rounds_down_and_goes_negative_after_expiry(monkeypatch):
    cert, _ = pki.build_root_ca()
    end = cert.not_valid_after_utc
    ten_days = datetime.timedelta(days=10)
    one_second = datetime.timedelta(seconds=1)

    # The boundary: exactly ten days before the end counts 10, one second less 9.
    assert pki.days_left(cert, now=end - ten_days) == 10
    assert pki.days_left(cert, now=end - ten_days + one_second) == 9
    assert pki.days_left(cert, now=end + one_second) == -1
    # Without `now` it reads the PKI clock.
    monkeypatch.setattr(pki, "_now", lambda: end + datetime.timedelta(days=3))
    assert pki.days_left(cert) == -3


# --- Key serialization (cold encrypted root, D7) ----------------------------


def test_root_key_encrypted_roundtrip_and_wrong_passphrase_fails():
    _, root_key = pki.build_root_ca()
    pem = pki.key_to_pem(root_key, passphrase=b"correct horse")
    assert b"ENCRYPTED" in pem
    loaded = pki.key_from_pem(pem, passphrase=b"correct horse")
    assert loaded.private_numbers().private_value == root_key.private_numbers().private_value
    with pytest.raises((ValueError, TypeError)):
        pki.key_from_pem(pem, passphrase=b"wrong")


def test_intermediate_key_unencrypted_for_unattended_signing():
    root_cert, root_key = pki.build_root_ca()
    _, inter_key = pki.build_intermediate_ca("internal", root_cert, root_key)
    pem = pki.key_to_pem(inter_key)  # no passphrase
    assert b"ENCRYPTED" not in pem
    loaded = pki.key_from_pem(pem)
    assert loaded.private_numbers().private_value == inter_key.private_numbers().private_value


def test_chain_pem_order():
    root_cert, root_key = pki.build_root_ca()
    inter_cert, _ = pki.build_intermediate_ca("tunnel", root_cert, root_key)
    bundle = pki.chain_pem(inter_cert, root_cert)
    parsed = x509.load_pem_x509_certificates(bundle)
    assert [c.subject for c in parsed] == [inter_cert.subject, root_cert.subject]


# --- Root renewal (R-1021) ---------------------------------------------------


def _device_leaf(inter_cert, inter_key) -> x509.Certificate:
    csr, _ = _csr("agent-srv-01")
    spec = pki.LeafSpec(
        lifetime_days=pki.LEAF_DAYS_NATIVE,
        client_auth=True,
        server_auth=False,
        subject_cn="agent-srv-01",
        scope="tunnel",
        dns_names=("agent-srv-01",),
    )
    return pki.sign_leaf(csr, inter_cert, inter_key, spec)


def _client_verifier(*anchors: x509.Certificate):
    now = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
    return PolicyBuilder().store(Store(list(anchors))).time(now).build_client_verifier()


def _ski(cert: x509.Certificate) -> bytes:
    return cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest


def _spki(cert: x509.Certificate) -> bytes:
    return cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def test_a_root_label_is_appended_to_the_cn():
    root_cert, _ = pki.build_root_ca(label="2036-02-01")
    assert pki.read_identity(root_cert)[0] == "AdminHelper Root CA 2036-02-01"


def test_the_cross_certificate_is_the_new_root_signed_by_the_old_one(monkeypatch):
    # The old root has 100 days left, the cross certificate ends with it.
    old_root, old_key = _minted_at(monkeypatch, 100 - pki.VALIDITY_DAYS_ROOT, pki.build_root_ca)
    new_root, _ = pki.build_root_ca(label="2026-11-02")

    cross = pki.build_cross_cert(new_root, old_root, old_key)

    assert cross.subject == new_root.subject and cross.issuer == old_root.subject
    assert _spki(cross) == _spki(new_root) and _ski(cross) == _ski(new_root)
    aki = cross.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value
    assert aki.key_identifier == _ski(old_root)
    bc = cross.extensions.get_extension_for_class(x509.BasicConstraints)
    assert bc.critical and bc.value.ca and bc.value.path_length == 1
    assert cross.not_valid_after_utc == old_root.not_valid_after_utc
    cross.verify_directly_issued_by(old_root)
    assert pki.cross_problem(cross, new_root, old_root) is None


def test_a_client_that_trusts_only_the_old_root_reaches_a_leaf_of_the_new_one():
    old_root, old_key = pki.build_root_ca()
    new_root, new_key = pki.build_root_ca(label="2026-11-02")
    cross = pki.build_cross_cert(new_root, old_root, old_key)
    inter_cert, inter_key = pki.build_intermediate_ca("tunnel", new_root, new_key, label="x")
    leaf = _device_leaf(inter_cert, inter_key)

    chain = _client_verifier(old_root).verify(leaf, [inter_cert, cross]).chain
    assert chain == [leaf, inter_cert, cross, old_root]
    # One that trusts the new root stops there, with or without the cross certificate.
    chain = _client_verifier(new_root).verify(leaf, [inter_cert, cross]).chain
    assert chain == [leaf, inter_cert, new_root]
    # Without the cross certificate the old root does not reach the new hierarchy.
    with pytest.raises(VerificationError):
        _client_verifier(old_root).verify(leaf, [inter_cert])


def test_an_expired_old_root_signs_no_cross_certificate(monkeypatch):
    old_root, old_key = _minted_at(monkeypatch, -pki.VALIDITY_DAYS_ROOT - 1, pki.build_root_ca)
    new_root, _ = pki.build_root_ca(label="2026-11-02")

    with pytest.raises(pki.IssuerNotValid, match="expired"):
        pki.build_cross_cert(new_root, old_root, old_key)


def test_cross_problem_names_what_is_wrong():
    old_root, old_key = pki.build_root_ca()
    new_root, _ = pki.build_root_ca(label="2026-11-02")
    other_root, other_key = pki.build_root_ca(label="other")

    foreign = pki.build_cross_cert(new_root, other_root, other_key)
    assert "not signed by root 'AdminHelper Root CA'" in pki.cross_problem(
        foreign, new_root, old_root
    )
    other_cross = pki.build_cross_cert(other_root, old_root, old_key)
    assert "name and key of root" in pki.cross_problem(other_cross, new_root, old_root)
    # The new root itself carries its name and key, but is no cross certificate.
    assert pki.cross_problem(new_root, new_root, old_root) == "it is not a CA with path_length=1"
