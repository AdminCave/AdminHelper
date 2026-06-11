# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ECDSA two-tier PKI engine for the ca-issuer (ADR 0001).

Pure crypto: builds a Root CA, scoped Intermediate CAs, and signs leaf
certificates from CSRs. No disk, no DB, no env — storage and orchestration
live in the issuer layer. ECDSA P-256 throughout (D10: fits the 2560-byte
Windows-keyring limit; faster than RSA for short-lived certs).

Hierarchy (ADR 0001 §3.1):

    Root CA  -> Intermediate "tunnel"   (frps + agent/visitor mTLS)
             -> Intermediate "access"   (web/desktop server leaf + client certs)
             -> Intermediate "internal" (future service-to-service mTLS)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# --- Policy constants --------------------------------------------------------

CURVE = ec.SECP256R1  # P-256 (D10)
_HASH = hashes.SHA256()

VALIDITY_DAYS_ROOT = 3650  # 10 years, cold
VALIDITY_DAYS_INTERMEDIATE = 1825  # 5 years
# Leaf lifetimes per audience (D5): native short + auto-renew, browser long + manual.
LEAF_DAYS_NATIVE = 90
LEAF_DAYS_BROWSER = 365

SCOPES = ("tunnel", "access", "internal")

_ORG = "AdminHelper"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _name(common_name: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, _ORG),
        ]
    )


# --- Keys --------------------------------------------------------------------


def generate_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(CURVE())


def key_to_pem(key: ec.EllipticCurvePrivateKey, passphrase: bytes | None = None) -> bytes:
    """Serialize a private key to PEM. With a passphrase the key is encrypted
    at rest (used for the cold Root key, D7); intermediates stay unencrypted
    so they can sign unattended (protected by container isolation + 0600)."""
    if passphrase:
        enc: serialization.KeySerializationEncryption = serialization.BestAvailableEncryption(
            passphrase
        )
    else:
        enc = serialization.NoEncryption()
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=enc,
    )


def key_from_pem(pem: bytes, passphrase: bytes | None = None) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem, password=passphrase)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("Erwartet wurde ein EC-Schlüssel")
    return key


def cert_to_pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def cert_from_pem(pem: bytes) -> x509.Certificate:
    return x509.load_pem_x509_certificate(pem)


def chain_pem(*certs: x509.Certificate) -> bytes:
    """Concatenate certs in the given order (leaf first for a presentation
    fullchain, root last for a trust bundle)."""
    return b"".join(cert_to_pem(c) for c in certs)


# --- CA construction ---------------------------------------------------------


def _ca_key_usage() -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=True,
        key_cert_sign=True,
        crl_sign=True,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        encipher_only=False,
        decipher_only=False,
    )


def build_root_ca(
    common_name: str = "AdminHelper Root CA",
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    key = generate_key()
    name = _name(common_name)
    now = _now()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=VALIDITY_DAYS_ROOT))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(_ca_key_usage(), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, _HASH)
    )
    return cert, key


def build_intermediate_ca(
    scope: str,
    root_cert: x509.Certificate,
    root_key: ec.EllipticCurvePrivateKey,
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    if scope not in SCOPES:
        raise ValueError(f"Unbekannter Scope '{scope}'. Erlaubt: {', '.join(SCOPES)}")
    key = generate_key()
    subject = _name(f"AdminHelper {scope.capitalize()} Intermediate")
    now = _now()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(root_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=VALIDITY_DAYS_INTERMEDIATE))
        # path_length=0: this intermediate may sign leaves but no further CAs.
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_ca_key_usage(), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
            critical=False,
        )
        .sign(root_key, _HASH)
    )
    return cert, key


# --- Leaf signing ------------------------------------------------------------


@dataclass(frozen=True)
class LeafSpec:
    """What kind of leaf to mint from a CSR."""

    lifetime_days: int
    server_auth: bool = False
    client_auth: bool = True
    # Optional SAN override; if empty the CSR's SAN (or none) is used.
    dns_names: tuple[str, ...] = ()
    ip_addresses: tuple[str, ...] = ()


def sign_leaf(
    csr: x509.CertificateSigningRequest,
    issuer_cert: x509.Certificate,
    issuer_key: ec.EllipticCurvePrivateKey,
    spec: LeafSpec,
) -> x509.Certificate:
    """Sign a CSR into a non-CA leaf under the given intermediate.

    The subject comes from the CSR; the public key comes from the CSR (the
    private key never leaves the requesting device). EKU/KeyUsage and lifetime
    are dictated by the issuer per `spec` — the CSR cannot widen them."""
    if not csr.is_signature_valid:
        raise ValueError("CSR-Signatur ist ungültig")

    ekus = []
    if spec.server_auth:
        ekus.append(ExtendedKeyUsageOID.SERVER_AUTH)
    if spec.client_auth:
        ekus.append(ExtendedKeyUsageOID.CLIENT_AUTH)
    if not ekus:
        raise ValueError("Leaf braucht mindestens server_auth oder client_auth")

    now = _now()
    builder = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(issuer_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=spec.lifetime_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            # ECDSA: digital_signature only (no key_encipherment — that's RSA).
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=False,
                crl_sign=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage(ekus), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False,
        )
    )

    san = _build_san(spec)
    if san is not None:
        builder = builder.add_extension(san, critical=False)

    return builder.sign(issuer_key, _HASH)


def _build_san(spec: LeafSpec) -> x509.SubjectAlternativeName | None:
    import ipaddress

    entries: list[x509.GeneralName] = [x509.DNSName(d) for d in spec.dns_names]
    for ip in spec.ip_addresses:
        entries.append(x509.IPAddress(ipaddress.ip_address(ip)))
    return x509.SubjectAlternativeName(entries) if entries else None
