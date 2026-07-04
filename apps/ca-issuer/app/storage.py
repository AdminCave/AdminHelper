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

import datetime
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec

from app import pki

logger = logging.getLogger("ca-issuer.storage")

# Re-mint a provisioned server leaf (gateway/frps) once it is past this much of
# its lifetime. Unlike native client certs these leaves have no client-side
# auto-renew, so a stack restart refreshes them through this check — well before
# they expire and take :443/:8444 (or frps) down (F4). Clients pin the Root, so
# the rotation is transparent (D2).
LEAF_REMINT_FRACTION = 0.5


def _leaf_needs_remint(fullchain_path: Path, fraction: float = LEAF_REMINT_FRACTION) -> bool:
    """True if the leaf in fullchain_path is missing, unreadable, or already past
    `fraction` of its validity, so the caller re-mints it on boot. The first cert
    in the fullchain is the leaf."""
    try:
        leaf = x509.load_pem_x509_certificate(fullchain_path.read_bytes())
    except (OSError, ValueError):
        return True
    total = (leaf.not_valid_after_utc - leaf.not_valid_before_utc).total_seconds()
    if total <= 0:
        return True
    elapsed = (
        datetime.datetime.now(datetime.timezone.utc) - leaf.not_valid_before_utc
    ).total_seconds()
    return elapsed >= total * fraction


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


def _classify_sans(primary: str, extra_sans: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a primary name + EXTRA_SANS into (dns_names, ip_addresses). localhost
    + 127.0.0.1 are always added so local/compose access validates against the
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

    add(primary)
    add("localhost")
    add("127.0.0.1")
    for entry in extra_sans.split(","):
        add(entry)
    return tuple(dns), tuple(ips)


def _provision_server_material(
    out_dir: Path,
    inter: Intermediate,
    primary: str,
    extra_sans: str,
    *,
    bundle_name: str,
    cert_name: str,
    key_name: str,
    label: str,
    extra_trust: tuple[Intermediate, ...] = (),
) -> None:
    """Shared core for the gateway + frps server-cert provisioning (audit 2.9):
    they differ only in file names, the signing intermediate, and any extra trust.
    Idempotent — the trust bundle is always refreshed (cheap, tracks rotations);
    the leaf is kept across restarts but re-minted once past half its life (F4) so
    it never expires under a long-running stack."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Trust bundle = the signing intermediate's chain (root already in it) plus any
    # extra trust intermediates (e.g. frps also trusting the access chain for the
    # STCP visitor). Always (re)written so it follows the current hierarchy.
    bundle = inter.chain + b"".join(pki.cert_to_pem(i.cert) for i in extra_trust)
    (out_dir / bundle_name).write_bytes(bundle)

    cert_path = out_dir / cert_name
    key_path = out_dir / key_name
    if cert_path.exists() and key_path.exists() and not _leaf_needs_remint(cert_path):
        return

    dns_names, ip_addresses = _classify_sans(primary, extra_sans)
    leaf, leaf_key = pki.build_server_leaf(inter.cert, inter.key, primary, dns_names, ip_addresses)
    # fullchain = leaf + signing intermediate (what the server presents on the wire).
    cert_path.write_bytes(pki.cert_to_pem(leaf) + pki.cert_to_pem(inter.cert))
    _write_private(key_path, pki.key_to_pem(leaf_key))
    logger.info("%s provisioniert (CN=%s, DNS=%s, IP=%s)", label, primary, dns_names, ip_addresses)


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
    the trust bundle is always refreshed (cheap, tracks rotations); the leaf is
    kept across restarts but re-minted once past half its life (F4) so it never
    expires under a long-running stack and takes the gateway down."""
    _provision_server_material(
        out_dir,
        access,
        domain,
        extra_sans,
        bundle_name="client-ca.pem",
        cert_name="gateway-fullchain.pem",
        key_name="gateway.key",
        label="Gateway-Cert",
    )


def ensure_frps_cert(
    out_dir: Path,
    tunnel: Intermediate,
    server_addr: str,
    extra_sans: str = "",
    extra_trust: tuple[Intermediate, ...] = (),
) -> None:
    """Provision the frps server TLS material under the tunnel intermediate
    (ADR 0001 §3.1 / A7). frps mounts these read-only:
        ca.crt    tunnel intermediate + root (+ extra_trust intermediates)
        frps.crt  server leaf + tunnel intermediate (server_auth, SAN=server_addr)
        frps.key  the leaf's private key (0600)

    ``extra_trust`` widens the client-cert trust beyond the tunnel scope: the
    desktop STCP *visitor* presents its enrolled **access** identity (F2 / ADR
    0001 D8 — the frp plane accepts both the agent's tunnel cert and the human's
    access cert; the real per-tunnel authz is the STCP secretKey + server-side
    bundle filtering, not the cert scope). The frps server leaf stays tunnel-signed.

    The CA private key never reaches the internet-facing frps — only the public
    chain (the GHSA-rv39 master/published split, now under the unified PKI).
    Idempotent like the gateway cert; re-minted once past half its life (F4)."""
    _provision_server_material(
        out_dir,
        tunnel,
        server_addr,
        extra_sans,
        bundle_name="ca.crt",
        cert_name="frps.crt",
        key_name="frps.key",
        label="frps-Cert",
        extra_trust=extra_trust,
    )
