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
