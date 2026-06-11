# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""On-disk persistence of the PKI hierarchy.

Layout under PKI_DIR:
    root.crt              root cert (public)
    root.key.enc          root key, passphrase-encrypted (cold, D7)
    <scope>.crt / .key    intermediate cert + unencrypted key (0600, online)
    <scope>-chain.pem     <scope> intermediate + root (trust bundle)

Normal leaf signing only ever loads an intermediate (cert + key) — the root is
decrypted solely to create/rotate intermediates.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec

from app import pki

logger = logging.getLogger("ca-issuer.storage")


@dataclass
class Intermediate:
    scope: str
    cert: x509.Certificate
    key: ec.EllipticCurvePrivateKey
    chain: bytes  # intermediate + root (PEM), for trust distribution / fullchain


def _write_private(path: Path, pem: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, pem)
    finally:
        os.close(fd)
    try:
        path.chmod(0o600)  # O_CREAT leaves an existing file's mode unchanged
    except OSError as exc:
        logger.warning("Konnte Key-Permissions nicht auf 0600 setzen (%s): %s", path, exc)


def ensure_hierarchy(pki_dir: Path, root_passphrase: bytes | None) -> dict[str, Intermediate]:
    """Idempotent: generate Root + all scoped intermediates on first boot,
    otherwise load the existing intermediates. Returns {scope: Intermediate}.

    The root key is required (to encrypt it) only when creating the hierarchy;
    on later boots only the intermediates are loaded — the root stays cold."""
    pki_dir.mkdir(parents=True, exist_ok=True)
    try:
        pki_dir.chmod(0o700)
    except OSError as exc:
        logger.warning("Konnte PKI-Dir nicht auf 0700 setzen: %s", exc)

    root_crt = pki_dir / "root.crt"
    root_key_enc = pki_dir / "root.key.enc"

    if not (root_crt.exists() and root_key_enc.exists()):
        if not root_passphrase:
            raise RuntimeError(
                "CA_ROOT_PASSPHRASE muss gesetzt sein, um die PKI erstmalig zu erzeugen."
            )
        logger.warning("Keine PKI gefunden — erzeuge Root + Intermediates (einmalig).")
        root_cert, root_key = pki.build_root_ca()
        root_crt.write_bytes(pki.cert_to_pem(root_cert))
        _write_private(root_key_enc, pki.key_to_pem(root_key, passphrase=root_passphrase))
        for scope in pki.SCOPES:
            inter_cert, inter_key = pki.build_intermediate_ca(scope, root_cert, root_key)
            (pki_dir / f"{scope}.crt").write_bytes(pki.cert_to_pem(inter_cert))
            _write_private(pki_dir / f"{scope}.key", pki.key_to_pem(inter_key))
            (pki_dir / f"{scope}-chain.pem").write_bytes(pki.chain_pem(inter_cert, root_cert))
        logger.info("PKI erzeugt: Root + %s", ", ".join(pki.SCOPES))

    root_cert = pki.cert_from_pem(root_crt.read_bytes())
    out: dict[str, Intermediate] = {}
    for scope in pki.SCOPES:
        cert = pki.cert_from_pem((pki_dir / f"{scope}.crt").read_bytes())
        key = pki.key_from_pem((pki_dir / f"{scope}.key").read_bytes())
        chain = (pki_dir / f"{scope}-chain.pem").read_bytes()
        out[scope] = Intermediate(scope=scope, cert=cert, key=key, chain=chain)
    return out


def _gateway_sans(domain: str, extra_sans: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split DOMAIN + EXTRA_SANS into (dns_names, ip_addresses). localhost +
    127.0.0.1 are always added so local/compose access validates against the
    pinned Root."""
    import ipaddress

    dns: list[str] = []
    ips: list[str] = []

    def add(entry: str) -> None:
        entry = entry.strip()
        if not entry:
            return
        try:
            ipaddress.ip_address(entry)
            if entry not in ips:
                ips.append(entry)
        except ValueError:
            if entry not in dns:
                dns.append(entry)

    add(domain)
    add("localhost")
    add("127.0.0.1")
    for entry in extra_sans.split(","):
        add(entry)
    return tuple(dns), tuple(ips)


def ensure_gateway_cert(
    out_dir: Path, access: Intermediate, domain: str, extra_sans: str = ""
) -> None:
    """Provision the gateway's TLS material into a shared volume (ADR 0001 §3.2).

    Writes three files the gateway mounts read-only:
        client-ca.pem            access intermediate + root (verify client certs)
        gateway-fullchain.pem    server leaf + access intermediate (TLS terminate)
        gateway.key              the leaf's private key (0600)

    The leaf chains to the pinned Root so native clients (which pin the Root and
    validate every leaf against it, D2) accept the gateway on :443. Idempotent:
    the trust bundle is always refreshed (cheap, tracks rotations), the leaf is
    minted only when absent so restarts keep a stable cert."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Trust bundle for client-cert verification — always (re)written so it
    # follows the current hierarchy even if intermediates were rotated.
    (out_dir / "client-ca.pem").write_bytes(access.chain)

    fullchain = out_dir / "gateway-fullchain.pem"
    key_path = out_dir / "gateway.key"
    if fullchain.exists() and key_path.exists():
        return

    dns_names, ip_addresses = _gateway_sans(domain, extra_sans)
    leaf, leaf_key = pki.build_server_leaf(access.cert, access.key, domain, dns_names, ip_addresses)
    # fullchain = leaf + access intermediate (what nginx presents on :443).
    fullchain.write_bytes(pki.cert_to_pem(leaf) + pki.cert_to_pem(access.cert))
    _write_private(key_path, pki.key_to_pem(leaf_key))
    logger.info(
        "Gateway-Cert provisioniert (CN=%s, DNS=%s, IP=%s)", domain, dns_names, ip_addresses
    )
