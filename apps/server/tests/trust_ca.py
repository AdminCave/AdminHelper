# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A test CA for the issuer check (R-1009): one root and one intermediate per scope, as the
ca-issuer keeps them, and the trust directory the server reads (CA_TRUST_DIR). Built once per
process; conftest points every test at its directory."""

import datetime
from functools import cache
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

SCOPES = ("tunnel", "access", "internal")


def _name(cn: str, ou: str | None = None) -> x509.Name:
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, cn)]
    if ou is not None:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, ou))
    return x509.Name(attrs)


def make_ca(
    subject: x509.Name,
    issuer: x509.Name | None = None,
    signer: ec.EllipticCurvePrivateKey | None = None,
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """A CA certificate, self-signed without ``issuer``/``signer``."""
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer or subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(signer or key, hashes.SHA256())
    )
    return cert, key


@cache
def root() -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    return make_ca(_name("Test Root CA"))


def intermediate_of(cn: str) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """An intermediate of the test root that no trust file lists unless written there."""
    root_cert, root_key = root()
    return make_ca(_name(cn), root_cert.subject, root_key)


@cache
def intermediate(scope: str) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    return intermediate_of(f"Test {scope} intermediate")


def leaf(
    cn: str,
    ou: str | None,
    not_before: datetime.datetime | None = None,
    days: int = 1,
    issuer: tuple[x509.Certificate, ec.EllipticCurvePrivateKey] | None = None,
) -> x509.Certificate:
    """A client leaf as the ca-issuer issues it: signed by the intermediate of its scope
    (or ``issuer``); a leaf of no known scope is self-signed. ``not_before`` (UTC) defaults
    to now."""
    key = ec.generate_private_key(ec.SECP256R1())
    if issuer is None and ou in SCOPES:
        issuer = intermediate(ou)
    start = not_before or datetime.datetime.now(datetime.timezone.utc)
    subject = _name(cn, ou)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer[0].subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + datetime.timedelta(days=days))
    )
    return builder.sign(issuer[1] if issuer else key, hashes.SHA256())


def pem(*certs: x509.Certificate) -> bytes:
    return b"".join(c.public_bytes(serialization.Encoding.PEM) for c in certs)


def write_trust_dir(directory: Path) -> Path:
    """<scope>.pem with the scope's intermediate, as the ca-issuer writes it."""
    directory.mkdir(parents=True, exist_ok=True)
    for scope in SCOPES:
        (directory / f"{scope}.pem").write_bytes(pem(intermediate(scope)[0]))
    return directory
