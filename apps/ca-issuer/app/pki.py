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
# Gateway TLS leaf: long-lived because the gateway has no auto-renew yet (a
# later task). The issuer re-provisions it on demand; until then a deploy/restart
# rotates it (clients pin the Root, not the leaf, so rotation is transparent).
LEAF_DAYS_GATEWAY = 365

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
    # Identity is dictated by the issuer (from the server-minted grant), NOT
    # taken from the CSR — otherwise a client could request a cert for any
    # identity. If subject_cn is None the CSR's subject is used (server-leaf case).
    subject_cn: str | None = None
    # Scope ("tunnel"/"access"/"internal") embedded as an OU so /renew can read
    # it back from the verified client cert without a DB lookup.
    scope: str | None = None
    dns_names: tuple[str, ...] = ()
    ip_addresses: tuple[str, ...] = ()


def _leaf_subject(spec: LeafSpec, csr: x509.CertificateSigningRequest) -> x509.Name:
    if spec.subject_cn is None:
        return csr.subject
    attrs = [
        x509.NameAttribute(NameOID.COMMON_NAME, spec.subject_cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, _ORG),
    ]
    if spec.scope:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, spec.scope))
    return x509.Name(attrs)


def read_identity(cert: x509.Certificate) -> tuple[str | None, str | None]:
    """Extract (CN, scope-OU) from a leaf — used on renewal to re-issue the
    same identity/scope from the verified client cert."""

    def _first(oid):
        attrs = cert.subject.get_attributes_for_oid(oid)
        return attrs[0].value if attrs else None

    return _first(NameOID.COMMON_NAME), _first(NameOID.ORGANIZATIONAL_UNIT_NAME)


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
        .subject_name(_leaf_subject(spec, csr))
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


def build_server_leaf(
    issuer_cert: x509.Certificate,
    issuer_key: ec.EllipticCurvePrivateKey,
    common_name: str,
    dns_names: tuple[str, ...] = (),
    ip_addresses: tuple[str, ...] = (),
    lifetime_days: int = LEAF_DAYS_GATEWAY,
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Mint a fresh server-auth leaf (key generated here) under the given
    intermediate. Unlike the CSR-driven client flow, the issuer both creates the
    key and signs the cert — used to provision the gateway's TLS material, which
    no on-device CSR exists for (ADR 0001 §3.2). The gateway thereby holds a
    leaf, never a signing key (D6 intact)."""
    key = generate_key()
    csr = x509.CertificateSigningRequestBuilder().subject_name(_name(common_name)).sign(key, _HASH)
    spec = LeafSpec(
        lifetime_days=lifetime_days,
        server_auth=True,
        client_auth=False,
        subject_cn=common_name,
        dns_names=tuple(dns_names),
        ip_addresses=tuple(ip_addresses),
    )
    return sign_leaf(csr, issuer_cert, issuer_key, spec), key


def _build_san(spec: LeafSpec) -> x509.SubjectAlternativeName | None:
    import ipaddress

    entries: list[x509.GeneralName] = [x509.DNSName(d) for d in spec.dns_names]
    for ip in spec.ip_addresses:
        entries.append(x509.IPAddress(ipaddress.ip_address(ip)))
    return x509.SubjectAlternativeName(entries) if entries else None
