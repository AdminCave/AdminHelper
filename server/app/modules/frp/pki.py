"""PKI-Management fuer FRP mTLS — CA, Server- und Client-Zertifikate."""

import datetime
import logging
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import FRP_CONFIG_DIR

logger = logging.getLogger(__name__)

PKI_DIR = FRP_CONFIG_DIR / "pki"
VALIDITY_DAYS_CA = 3650  # 10 Jahre
VALIDITY_DAYS_CERT = 365  # 1 Jahr


def _ensure_pki_dir() -> Path:
    PKI_DIR.mkdir(parents=True, exist_ok=True)
    return PKI_DIR


def _generate_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=4096)


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def get_pki_status() -> dict:
    """Gibt den aktuellen PKI-Status zurueck."""
    d = _ensure_pki_dir()
    ca_cert = d / "ca.crt"
    ca_key = d / "ca.key"
    server_cert = d / "frps.crt"

    status = {
        "pkiDir": str(d),
        "caExists": ca_cert.exists() and ca_key.exists(),
        "serverCertExists": server_cert.exists(),
        "caExpiry": None,
        "serverCertExpiry": None,
        "clientCerts": [],
    }

    if status["caExists"]:
        cert = x509.load_pem_x509_certificate(ca_cert.read_bytes())
        status["caExpiry"] = cert.not_valid_after_utc.isoformat()

    if status["serverCertExists"]:
        cert = x509.load_pem_x509_certificate(server_cert.read_bytes())
        status["serverCertExpiry"] = cert.not_valid_after_utc.isoformat()

    # Client-Certs auflisten
    for f in sorted(d.glob("*.crt")):
        if f.name in ("ca.crt", "frps.crt"):
            continue
        name = f.stem
        cert = x509.load_pem_x509_certificate(f.read_bytes())
        status["clientCerts"].append({
            "name": name,
            "expiry": cert.not_valid_after_utc.isoformat(),
        })

    return status


def generate_ca(common_name: str = "SRM FRP CA") -> dict:
    """Generiert eine neue CA (ueberschreibt bestehende!)."""
    d = _ensure_pki_dir()
    key = _generate_key()
    now = datetime.datetime.now(datetime.timezone.utc)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Simple Remote Manager"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=VALIDITY_DAYS_CA))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_cert_sign=True, crl_sign=True,
            content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False,
            encipher_only=False, decipher_only=False,
        ), critical=True)
        .sign(key, hashes.SHA256())
    )

    _write_key(d / "ca.key", key)
    _write_cert(d / "ca.crt", cert)
    logger.info("CA generiert: %s (gueltig bis %s)", common_name, cert.not_valid_after_utc)

    return {
        "commonName": common_name,
        "expiry": cert.not_valid_after_utc.isoformat(),
        "certPath": str(d / "ca.crt"),
        "keyPath": str(d / "ca.key"),
    }


def _load_ca() -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    d = _ensure_pki_dir()
    ca_cert = x509.load_pem_x509_certificate((d / "ca.crt").read_bytes())
    ca_key = serialization.load_pem_private_key((d / "ca.key").read_bytes(), password=None)
    return ca_cert, ca_key


def generate_server_cert(server_addr: str) -> dict:
    """Generiert ein Server-Zertifikat fuer frps, signiert von der CA."""
    import ipaddress

    ca_cert, ca_key = _load_ca()
    d = _ensure_pki_dir()
    key = _generate_key()
    now = datetime.datetime.now(datetime.timezone.utc)

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, server_addr),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Simple Remote Manager"),
    ])

    # IP-Adressen muessen als IPAddress-SAN eingetragen werden, nicht als DNSName
    san_entries: list[x509.GeneralName] = []
    try:
        san_entries.append(x509.IPAddress(ipaddress.ip_address(server_addr)))
    except ValueError:
        san_entries.append(x509.DNSName(server_addr))

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=VALIDITY_DAYS_CERT))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.ExtendedKeyUsage([
            x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
        ]), critical=False)
    )

    cert = builder.sign(ca_key, hashes.SHA256())

    _write_key(d / "frps.key", key)
    _write_cert(d / "frps.crt", cert)
    logger.info("Server-Cert generiert fuer: %s", server_addr)

    return {
        "commonName": server_addr,
        "expiry": cert.not_valid_after_utc.isoformat(),
        "certPath": str(d / "frps.crt"),
        "keyPath": str(d / "frps.key"),
    }


import re as _re

_VALID_CLIENT_NAME = _re.compile(r'^[a-zA-Z0-9._-]+$')


def generate_client_cert(client_name: str) -> dict:
    """Generiert ein Client-Zertifikat fuer einen frpc-Host, signiert von der CA."""
    safe_name = Path(client_name).name
    if (
        not safe_name
        or safe_name != client_name
        or '..' in client_name
        or not _VALID_CLIENT_NAME.match(client_name)
        or len(client_name) > 64
    ):
        raise ValueError(f"Ungueltiger Client-Name: {client_name!r}")

    ca_cert, ca_key = _load_ca()
    d = _ensure_pki_dir()
    key = _generate_key()
    now = datetime.datetime.now(datetime.timezone.utc)

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, client_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Simple Remote Manager"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=VALIDITY_DAYS_CERT))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([
            x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
        ]), critical=False)
    )

    cert = cert.sign(ca_key, hashes.SHA256())

    _write_key(d / f"{client_name}.key", key)
    _write_cert(d / f"{client_name}.crt", cert)
    logger.info("Client-Cert generiert fuer: %s", client_name)

    return {
        "commonName": client_name,
        "expiry": cert.not_valid_after_utc.isoformat(),
        "certPath": str(d / f"{client_name}.crt"),
        "keyPath": str(d / f"{client_name}.key"),
    }
