# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""On-disk persistence of the PKI hierarchy.

Layout under PKI_DIR:
    root.crt              root cert (public)
    root.key.enc          root key, passphrase-encrypted (cold, D7)
    <scope>.crt / .key    intermediate cert + unencrypted key (0600, online)
    <scope>-chain.pem     <scope> intermediate + root (trust bundle)
    <scope>-retired.pem   optional: earlier <scope> intermediates, certificates
                          only (no keys), still trusted until they expire

Normal leaf signing only ever loads an intermediate (cert + key) — the root is
decrypted solely to create/rotate intermediates.
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import pki

_T = TypeVar("_T")

logger = logging.getLogger("ca-issuer.storage")

# Appended to every message about an intermediate's end (boot, signing, 503): the command
# of app/cli.py. Never to the root's: it issues intermediates under the root, not a root.
ROTATE_HINT = (
    "rotate with: docker compose run --rm --no-deps ca-issuer python -m app.cli "
    "rotate-intermediates"
)
# Said instead where an intermediate is not valid yet. It is valid from its issuing
# (pki.build_intermediate_ca), so this clock is behind the one that issued it. The cure is
# the clock, not a rotation: under this clock the rotation stops before it writes
# (rotation._rotate), as it would replace that intermediate without keeping it as retired.
CLOCK_HINT = (
    "check the host clock (NTP), it is behind the issuing of this intermediate; "
    "a rotation refuses to run under this clock"
)

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
    # Earlier intermediates of this scope from <scope>-retired.pem, newest first: valid,
    # of this scope under the root, never the current one. Verify only — no key here.
    retired: tuple[x509.Certificate, ...] = ()


def _write_private(path: Path, pem: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:  # buffered writer writes it all (no short write), closes the fd
        f.write(pem)
        f.flush()
        # fsync the CA key material: a crash/power-loss right after the write could otherwise leave
        # the key empty/truncated on disk while the .crt stays intact, breaking the next boot at
        # key_from_pem / an nginx cert-key mismatch — the system's most valuable material (4.86).
        os.fsync(f.fileno())
    try:
        path.chmod(0o600)  # O_CREAT leaves an existing file's mode unchanged
    except OSError as exc:
        # Fail closed: a private signing key we cannot lock down to 0600 must not be
        # used — abort boot rather than keep signing with a group/world-readable key
        # (the old fail-open path only logged a warning and continued) (3.49).
        raise RuntimeError(f"Key-Permissions 0600 nicht durchsetzbar ({path}): {exc}") from exc


def ensure_hierarchy(pki_dir: Path, root_passphrase: bytes | None) -> dict[str, Intermediate]:
    """Idempotent: generate Root + all scoped intermediates on first boot,
    otherwise load the existing intermediates. Returns {scope: Intermediate}.

    The root key is required (to encrypt it) only when creating the hierarchy;
    on later boots only the intermediates are loaded — the root stays cold.

    Every boot then checks what it loaded and raises RuntimeError (file, scope,
    reason) unless every file is readable, root.crt is self-signed and valid now and each
    intermediate is one of its scope under it (pki.intermediate_problem), valid now,
    matches its key and has the chain [intermediate, root].
    A root or intermediate with less than pki.EXPIRY_WARN_DAYS left is a WARNING. What
    concerns an intermediate's end (abort or WARNING) ends with ROTATE_HINT, the abort
    for one not valid yet with CLOCK_HINT.

    The optional <scope>-retired.pem adds the scope's earlier intermediates as
    Intermediate.retired. An entry that is not an intermediate of the scope under
    root.crt (pki.intermediate_problem) is left out with a WARNING (file, scope, CN,
    reason) and does not stop the boot; one that is outside its validity (INFO line) or
    equal to the current one is left out too. A file that is no PEM bundle raises."""
    pki_dir.mkdir(parents=True, exist_ok=True)
    try:
        pki_dir.chmod(0o700)
    except OSError as exc:
        logger.warning("Konnte PKI-Dir nicht auf 0700 setzen: %s", exc)

    root_crt = pki_dir / "root.crt"
    root_key_enc = pki_dir / "root.key.enc"

    expected = [root_crt, root_key_enc] + [
        pki_dir / name
        for scope in pki.SCOPES
        for name in (f"{scope}.crt", f"{scope}.key", f"{scope}-chain.pem")
    ]
    if not all(p.exists() for p in expected):
        # A partial dir (root present but an intermediate missing/half-written) means a crash
        # mid-first-boot (OOM, full volume, container stop). Skipping creation here would then
        # FileNotFoundError/ValueError in the load loop below — uncaught in lifespan, so uvicorn
        # never starts and the container restart-loops, fixable only by manual volume surgery.
        # Abort with a clear message instead (4.18).
        if root_crt.exists() and root_key_enc.exists():
            missing = [str(p) for p in expected if not p.exists()]
            raise RuntimeError(
                f"PKI-Verzeichnis unvollständig (abgebrochener First Boot?) — fehlend: {missing}. "
                "Volume prüfen; leeren, damit die PKI komplett neu erzeugt wird."
            )
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

    # Checked on every boot, the first included: an intermediate past its end, from another
    # root or beside a foreign key or chain would otherwise sign leaves no client accepts.
    now = pki._now()
    root = _read_pem(root_crt, pki.cert_from_pem, "a PEM certificate")
    if problem := _signature_problem(root, root):
        raise _invalid_hierarchy(f"{root_crt}: the root certificate is not self-signed ({problem})")
    if problem := _validity_problem(root, now):
        raise _invalid_hierarchy(f"{root_crt}: the root certificate is {problem}")

    out: dict[str, Intermediate] = {}
    for scope in pki.SCOPES:
        cert_path = pki_dir / f"{scope}.crt"
        key_path = pki_dir / f"{scope}.key"
        chain_path = pki_dir / f"{scope}-chain.pem"
        cert = _read_pem(cert_path, pki.cert_from_pem, "a PEM certificate", scope)
        key = _read_pem(key_path, pki.key_from_pem, "a PEM EC private key", scope)
        chain = chain_path.read_bytes()
        if problem := _signature_problem(cert, root):
            raise _invalid_hierarchy(
                f"scope {scope!r}, {cert_path}: not signed by {root_crt.name} ({problem})"
            )
        # The signature alone would let another scope's intermediate (with its own key and
        # chain) or a CA that may sign CAs pass as this scope's.
        if problem := pki.intermediate_problem(cert, scope, root):
            raise _invalid_hierarchy(f"scope {scope!r}, {cert_path}: {problem}")
        if problem := _validity_problem(cert, now):
            hint = ROTATE_HINT if now >= cert.not_valid_after_utc else CLOCK_HINT
            raise _invalid_hierarchy(
                f"scope {scope!r}, {cert_path}: the intermediate is {problem}", hint=hint
            )
        if not _holds_key(cert, key):
            raise _invalid_hierarchy(
                f"scope {scope!r}, {key_path}: not the private key of {cert_path.name}"
            )
        if not _chain_is(chain, [cert, root]):
            raise _invalid_hierarchy(
                f"scope {scope!r}, {chain_path}: not {cert_path.name} followed by {root_crt.name}"
            )
        # The check above compares only the certificates in the file; what goes out
        # (enroll responses, trust bundles) is rebuilt from the two checked ones.
        out[scope] = Intermediate(
            scope=scope,
            cert=cert,
            key=key,
            chain=pki.chain_pem(cert, root),
            retired=_load_retired(pki_dir / f"{scope}-retired.pem", scope, cert, root, now),
        )

    _warn_if_ending("root", root, now, "; renewing the root means enrolling every client again")
    for scope, inter in out.items():
        _warn_if_ending(f"intermediate {scope!r}", inter.cert, now, f"; {ROTATE_HINT}")
    return out


def _invalid_hierarchy(detail: str, hint: str = "") -> RuntimeError:
    # The hint goes last, without a full stop, so the command copies off the line as is.
    message = f"PKI hierarchy invalid — {detail}. The ca-issuer does not start with it"
    return RuntimeError(f"{message}; {hint}" if hint else f"{message}.")


def _write_atomic(path: Path, data: bytes) -> None:
    """Replace `path` by `data` atomically: a reader (nginx, frps) never sees a half
    file, and a failed write leaves the old one in place."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _read_pem(path: Path, load: Callable[[bytes], _T], what: str, scope: str = "") -> _T:
    try:
        return load(path.read_bytes())
    # TypeError: an encrypted key; UnsupportedAlgorithm: a curve or key type cryptography lacks.
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        where = f"scope {scope!r}, {path}" if scope else str(path)
        raise _invalid_hierarchy(f"{where}: not {what} ({exc})") from exc


def _load_retired(
    path: Path,
    scope: str,
    current: x509.Certificate,
    root: x509.Certificate,
    now: datetime.datetime,
) -> tuple[x509.Certificate, ...]:
    """The scope's retired intermediates from `path` (see ensure_hierarchy), newest first.
    A missing file or one without any text means none."""
    if not path.exists():
        return ()
    data = path.read_bytes()
    if not data.strip():
        return ()
    try:
        certs = x509.load_pem_x509_certificates(data)
    except ValueError as exc:
        raise _invalid_hierarchy(
            f"scope {scope!r}, {path}: not a PEM certificate bundle ({exc})"
        ) from exc
    der = serialization.Encoding.DER
    seen = {current.public_bytes(der)}
    retired: list[x509.Certificate] = []
    for cert in certs:
        name = pki.read_identity(cert)[0]
        if problem := pki.intermediate_problem(cert, scope, root):
            logger.warning("scope %r, %s: skipping retired %r, %s", scope, path.name, name, problem)
            continue
        if problem := _validity_problem(cert, now):
            logger.info(
                "scope %r, %s: skipping retired %r, it is %s", scope, path.name, name, problem
            )
            continue
        if cert.public_bytes(der) in seen:
            continue
        seen.add(cert.public_bytes(der))
        retired.append(cert)
    retired.sort(key=lambda c: c.not_valid_before_utc, reverse=True)
    return tuple(retired)


def _signature_problem(cert: x509.Certificate, issuer: x509.Certificate) -> str | None:
    """Why `issuer` did not sign `cert` (names or signature), or None if it did."""
    try:
        cert.verify_directly_issued_by(issuer)
    except InvalidSignature:
        return "the signature does not verify"
    except (ValueError, TypeError) as exc:
        return str(exc)
    return None


def _validity_problem(cert: x509.Certificate, now: datetime.datetime) -> str | None:
    """'expired …' or 'not yet valid …' if `now` is outside `cert`'s validity, else None
    (the same window pki signs in: notBefore <= now < notAfter)."""
    if now < cert.not_valid_before_utc:
        return f"not yet valid (notBefore {cert.not_valid_before_utc.isoformat()})"
    if now >= cert.not_valid_after_utc:
        return f"expired (notAfter {cert.not_valid_after_utc.isoformat()})"
    return None


def _chain_is(chain_pem: bytes, certs: list[x509.Certificate]) -> bool:
    """Whether the PEM chain holds exactly `certs` in order — compared as DER, so a
    restore that rewrote line endings or PEM wrapping still passes."""
    try:
        parsed = x509.load_pem_x509_certificates(chain_pem)
    except ValueError:
        return False
    der = serialization.Encoding.DER
    return [c.public_bytes(der) for c in parsed] == [c.public_bytes(der) for c in certs]


def _warn_if_ending(
    name: str, cert: x509.Certificate, now: datetime.datetime, note: str = ""
) -> None:
    left = pki.days_left(cert, now)
    if left < pki.EXPIRY_WARN_DAYS:
        logger.warning(
            "%s expires on %s (%d days left)%s",
            name,
            cert.not_valid_after_utc.isoformat(),
            left,
            note,
        )


def _classify_sans(primary: str, extra_sans: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a primary name + EXTRA_SANS into (dns_names, ip_addresses). localhost
    + 127.0.0.1 are always added so local/compose access validates against the
    pinned Root."""
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


def _pair_matches(cert_path: Path, key_path: Path) -> bool:
    """Whether the leaf in cert_path and the private key in key_path share a public key. Guards
    against a half-written pair (a new leaf beside an old key) left by a crash between the two
    writes — nginx rejects that with 'key values mismatch' and it never self-repairs (4.19)."""
    try:
        leaf = pki.cert_from_pem(cert_path.read_bytes())
        key = pki.key_from_pem(key_path.read_bytes())
    except (OSError, ValueError):
        return False
    return _holds_key(leaf, key)


def _leaf_signed_by(fullchain_path: Path, issuer: x509.Certificate) -> bool:
    """Whether `issuer` signed the leaf (the first cert) in fullchain_path."""
    try:
        leaf = x509.load_pem_x509_certificate(fullchain_path.read_bytes())
    except (OSError, ValueError):
        return False
    return _signature_problem(leaf, issuer) is None


def _presents_after_leaf(fullchain_path: Path, chain_pem: bytes) -> bool:
    """Whether the certificates after the leaf in fullchain_path are exactly those of chain_pem."""
    try:
        certs = x509.load_pem_x509_certificates(fullchain_path.read_bytes())
    except (OSError, ValueError):
        return False
    return _chain_is(chain_pem, certs[1:])


def _names_are(
    fullchain_path: Path, dns_names: tuple[str, ...], ip_addresses: tuple[str, ...]
) -> bool:
    """Whether the leaf in fullchain_path names exactly dns_names and ip_addresses, in any order."""
    try:
        leaf = x509.load_pem_x509_certificate(fullchain_path.read_bytes())
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False
    return set(san.get_values_for_type(x509.DNSName)) == set(dns_names) and set(
        san.get_values_for_type(x509.IPAddress)
    ) == {ipaddress.ip_address(ip) for ip in ip_addresses}


def _holds_key(cert: x509.Certificate, key: ec.EllipticCurvePrivateKey) -> bool:
    """Whether `key` is the private half of `cert`'s public key."""
    spki = serialization.PublicFormat.SubjectPublicKeyInfo
    pem = serialization.Encoding.PEM
    return cert.public_key().public_bytes(pem, spki) == key.public_key().public_bytes(pem, spki)


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
    send_root: bool = False,
    trust_root: bool = True,
) -> None:
    """Shared core for the gateway + frps server-cert provisioning (audit 2.9):
    they differ only in file names, the signing intermediate, any extra trust,
    whether the server presents the root after the intermediate (send_root) and
    whether the trust bundle carries the root (trust_root).
    Idempotent — the trust bundle is always refreshed (cheap, tracks rotations);
    the leaf is kept across restarts but re-minted once past half its life (F4) so
    it never expires under a long-running stack, once the current intermediate
    did not sign it (the first boot after a rotation), once the file does not
    present what follows the leaf now (a fullchain from before send_root), or once
    its names differ from primary + extra_sans (a changed DOMAIN or EXTRA_SANS)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Trust bundle = the signing intermediate's chain (with trust_root the root too) and its
    # retired intermediates, plus any extra trust intermediates (e.g. frps also
    # trusting the access chain for the STCP visitor) with theirs: a client cert from
    # before a rotation, sent without its chain (a browser .p12), still finds its
    # issuer until the retired one expires. Always (re)written so it follows the
    # current hierarchy.
    # Without trust_root the intermediates themselves are the anchors: a verifier that
    # takes any certificate in its pool as an anchor (Go's crypto/tls in frps) then
    # accepts only what a listed intermediate issued, so one dropped from the bundle
    # (rotate --compromised) is refused even when the client sends it along under the
    # same root. nginx (OpenSSL) needs the self-signed root as its anchor and keeps it.
    trusted = list(inter.retired)
    for extra in extra_trust:
        trusted += [extra.cert, *extra.retired]
    head = inter.chain if trust_root else pki.cert_to_pem(inter.cert)
    bundle = head + pki.chain_pem(*trusted)
    _write_atomic(out_dir / bundle_name, bundle)

    cert_path = out_dir / cert_name
    key_path = out_dir / key_name
    # What the server presents after its leaf: the signing intermediate, with send_root the
    # root too (inter.chain is exactly the two).
    presented = inter.chain if send_root else pki.cert_to_pem(inter.cert)
    # Also require the leaf and key to be a matching pair: a crash between writing the leaf and
    # the key leaves a NEW leaf beside the OLD key, which _leaf_needs_remint (0% aged) would pass
    # — nginx then fails with 'key values mismatch' and crash-loops for up to half the leaf life
    # with no self-repair. On a mismatch, fall through and re-mint the pair (4.19).
    # And require the current intermediate to have signed the leaf: after a rotation the server
    # would otherwise go on presenting a leaf of the retired intermediate (whose end also bounds
    # the leaf) until half its life; re-minting moves it onto the current one on the first boot.
    # And require the certificates after the leaf to be `presented`: a gateway fullchain from
    # before the root went along would otherwise fail a `--ca-fp` pinned on the root until half
    # the leaf's life.
    # And require the leaf to name what DOMAIN and EXTRA_SANS name now: a changed name would
    # otherwise reach the leaf only after half its life (R-0880).
    dns_names, ip_addresses = _classify_sans(primary, extra_sans)
    if (
        cert_path.exists()
        and key_path.exists()
        and not _leaf_needs_remint(cert_path)
        and _pair_matches(cert_path, key_path)
        and _leaf_signed_by(cert_path, inter.cert)
        and _presents_after_leaf(cert_path, presented)
        and _names_are(cert_path, dns_names, ip_addresses)
    ):
        return

    leaf, leaf_key = pki.build_server_leaf(inter.cert, inter.key, primary, dns_names, ip_addresses)
    # fullchain = leaf + `presented` (what the server sends on the wire).
    cert_path.write_bytes(pki.cert_to_pem(leaf) + presented)
    _write_private(key_path, pki.key_to_pem(leaf_key))
    logger.info("%s provisioniert (CN=%s, DNS=%s, IP=%s)", label, primary, dns_names, ip_addresses)


def ensure_gateway_cert(
    out_dir: Path, access: Intermediate, domain: str, extra_sans: str = ""
) -> None:
    """Provision the gateway's TLS material into a shared volume (ADR 0001 §3.2).

    Writes three files the gateway mounts read-only:
        client-ca.pem            access intermediate + root + retired access
                                 intermediates (verify client certs)
        gateway-fullchain.pem    server leaf + access intermediate + root
                                 (TLS terminate)
        gateway.key              the leaf's private key (0600)

    The leaf chains to the pinned Root so native clients (which pin the Root and
    validate every leaf against it, D2) accept the gateway on :443. The root goes
    along so an agent's `--ca-fp` can pin it: the agent looks for that fingerprint
    among the presented certificates (verifyAnchorFingerprint in
    apps/agent/internal/httpclient/httpclient.go), and unlike the intermediate the
    root outlives a rotation.

    Idempotent: the trust bundle is always refreshed (cheap, tracks rotations); the
    retired intermediates in it keep client certs from before a rotation accepted
    until they expire. The leaf is kept across restarts but re-minted once past half
    its life (F4) so it never expires under a long-running stack and takes the
    gateway down, on the first boot after a rotation, so it comes from the current
    access intermediate, and once a fullchain from before lacks the root."""
    _provision_server_material(
        out_dir,
        access,
        domain,
        extra_sans,
        bundle_name="client-ca.pem",
        cert_name="gateway-fullchain.pem",
        key_name="gateway.key",
        label="Gateway-Cert",
        send_root=True,
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
        ca.crt    tunnel intermediate + retired tunnel intermediates
                  (+ extra_trust intermediates, each with its retired ones);
                  no root, so the listed intermediates are frps's only anchors
        frps.crt  server leaf + tunnel intermediate (server_auth, SAN=server_addr)
        frps.key  the leaf's private key (0600)

    ``extra_trust`` widens the client-cert trust beyond the tunnel scope: the
    desktop STCP *visitor* presents its enrolled **access** identity (F2 / ADR
    0001 D8 — the frp plane accepts both the agent's tunnel cert and the human's
    access cert; the real per-tunnel authz is the STCP secretKey + server-side
    bundle filtering, not the cert scope). The frps server leaf stays tunnel-signed.

    The CA private key never reaches the internet-facing frps — only the public
    chain (the GHSA-rv39 master/published split, now under the unified PKI).
    Idempotent like the gateway cert: the retired intermediates keep agent and
    visitor certs from before a rotation accepted until they expire; the leaf is
    re-minted once past half its life (F4) and on the first boot after a
    rotation, so it comes from the current tunnel intermediate."""
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
        trust_root=False,
    )
