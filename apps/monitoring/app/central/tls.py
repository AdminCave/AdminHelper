# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensor tls of central checks (R-1224): handshake, chain, host name, lifetime.

The handshake itself verifies nothing (CERT_NONE), so that an untrusted or expired
certificate still yields its details. cryptography.x509.verification then checks
chain and name in one step against the certifi store, with the identity rules of
RFC 9525 (SAN only, a wildcard only as the whole leftmost label, an IP literal
against an iPAddress SAN). Thresholds are relative to the certificate's whole
lifetime, so a 90-day and a 6-day certificate are warned about alike. A trusted,
unexpired certificate also gets the periodic looks of ari and caa: what its CA says
about renewing it, and whether the domain still lets that CA issue the next one.
"""

from __future__ import annotations

import functools
import hashlib
import ipaddress
import socket
import ssl
import warnings
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import certifi
from cryptography import x509
from cryptography.utils import CryptographyDeprecationWarning
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

from app.central import ari, caa
from app.central.limits import LIMITS, SKIPPED_SPACING_MESSAGE, Limits, RunSkipped
from app.core.time import iso_utc

CONNECT_TIMEOUT_S = 5.0
HANDSHAKE_TIMEOUT_S = 10.0
# Addresses tried one after the other until one accepts the connection.
MAX_ADDRESSES = 3
WARN_PCT = 25.0
CRIT_PCT = 10.0
# Critical at the latest this long before the end, however short the lifetime.
CRIT_LEFT = timedelta(hours=12)
MAX_SANS = 20
MAX_TEXT = 200


@dataclass(frozen=True)
class SensorResult:
    """What a sensor of a central check found.

    `reached` says whether a global address of the target accepted the connection;
    the dispatcher decides from it what a failure means (rule 3 public/internal).
    """

    status: str
    message: str
    reached: bool
    metrics: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)


@functools.cache
def default_store() -> Store:
    """The certifi roots, loaded once per process."""
    with warnings.catch_warnings():
        # certifi carries a root with a non-positive serial; cryptography warns
        # about it on load and still accepts it, as the TLS libraries do.
        warnings.simplefilter("ignore", CryptographyDeprecationWarning)
        roots = x509.load_pem_x509_certificates(Path(certifi.where()).read_bytes())
    return Store(roots)


def probe(
    host: str,
    addresses: tuple[str, ...],
    port: int,
    prev: dict | None = None,
    *,
    store: Store | None = None,
    now: datetime | None = None,
    limits: Limits | None = None,
) -> SensorResult:
    """Connects to the first of `addresses` that answers and checks its certificate for `host`.

    `addresses` are the global addresses the rule public/internal handed on; nothing
    is resolved here. `prev` holds the details of the check's previous run for this
    host, with the ari and caa states. Raises RunSkipped when an address may not be
    contacted yet.
    """
    limits = limits or LIMITS
    now = now or datetime.now(timezone.utc)
    failures: list[str] = []
    for address in addresses[:MAX_ADDRESSES]:
        if not limits.address_turn(address):
            raise RunSkipped(SKIPPED_SPACING_MESSAGE)
        try:
            sock = socket.create_connection((address, port), timeout=CONNECT_TIMEOUT_S)
        except OSError as exc:
            failures.append(f"{address}: {_reason(exc)}")
            continue
        with sock:
            result, leaf = _check(sock, host, address, port, store or default_store(), now)
        return _daily(result, leaf, host, prev or {}, now)
    return SensorResult(
        "critical",
        f"no connection to {host} port {port}: " + "; ".join(failures),
        reached=False,
        details={"host": host, "port": port},
    )


def _check(
    sock: socket.socket,
    host: str,
    address: str,
    port: int,
    store: Store,
    now: datetime,
) -> tuple[SensorResult, x509.Certificate | None]:
    """The verdict and, when the certificate is trusted and not expired, its leaf."""
    details: dict = {"host": host, "address": address, "port": port}
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    sock.settimeout(HANDSHAKE_TIMEOUT_S)
    try:
        # No SNI for an IP literal (RFC 6066 forbids it).
        with context.wrap_socket(sock, server_hostname=None if literal else host) as tls:
            details["tls_version"] = tls.version()
            chain = tls.get_unverified_chain() or []
    except OSError as exc:  # ssl.SSLError and timeouts included
        message = f"TLS handshake failed: {_reason(exc)}"
        return SensorResult("critical", message, True, {}, details), None
    if not chain:
        return SensorResult("critical", "the server sent no certificate", True, {}, details), None
    try:
        certs = [x509.load_der_x509_certificate(der) for der in chain]
    except ValueError as exc:
        return SensorResult("critical", f"unreadable certificate: {exc}", True, {}, details), None
    leaf = certs[0]
    details.update(_describe(leaf, chain[0], len(certs)))

    not_before, not_after = leaf.not_valid_before_utc, leaf.not_valid_after_utc
    if now < not_before:
        message = f"certificate not valid before {iso_utc(not_before)}"
        return SensorResult("critical", message, True, {}, details), None
    left, total = not_after - now, not_after - not_before
    # Compared unrounded: 9.96 % is below the 10 % threshold, though shown as 10.0.
    pct = max(0.0, left / total * 100) if total > timedelta(0) else 0.0
    metrics = {"days_left": round(left.total_seconds() / 86400, 2), "lifetime_pct": round(pct, 1)}
    if left <= timedelta(0):
        message = f"certificate expired on {iso_utc(not_after)}"
        return SensorResult("critical", message, True, metrics, details), None

    subject = x509.IPAddress(literal) if literal else x509.DNSName(host)
    verifier = PolicyBuilder().store(store).time(now).build_server_verifier(subject)
    try:
        verifier.verify(leaf, certs[1:])
    except VerificationError as exc:
        message = f"certificate not trusted for {host}: {str(exc)[:MAX_TEXT]}"
        return SensorResult("critical", message, True, metrics, details), None

    summary = (
        f"valid until {iso_utc(not_after)} ({metrics['days_left']} days, "
        f"{metrics['lifetime_pct']} % of lifetime left)"
    )
    if left < CRIT_LEFT or pct < CRIT_PCT:
        status, message = "critical", f"certificate expires soon: {summary}"
    elif pct < WARN_PCT:
        status, message = "warning", f"certificate due for renewal: {summary}"
    else:
        status, message = "ok", f"certificate {summary}"
    return SensorResult(status, message, True, metrics, details), leaf


def _daily(
    result: SensorResult, leaf: x509.Certificate | None, host: str, prev: dict, now: datetime
) -> SensorResult:
    """Adds the ari and caa states; a finding of either makes an ok a warning."""
    if leaf is None:
        return result
    ari_state, ari_warning = ari.evaluate(leaf, _state(prev, "ari"), now)
    caa_state, caa_warning = caa.evaluate(leaf, host, ari.known_ca(leaf), _state(prev, "caa"), now)
    details = dict(result.details)
    for key, state in (("ari", ari_state), ("caa", caa_state)):
        if state is not None:
            details[key] = state
    findings = [w for w in (ari_warning, caa_warning) if w]
    if not findings:
        return replace(result, details=details)
    return replace(
        result,
        status="critical" if result.status == "critical" else "warning",
        message="; ".join([result.message, *findings]),
        details=details,
    )


def _state(prev: dict, key: str) -> dict | None:
    state = prev.get(key)
    return state if isinstance(state, dict) else None


def _describe(leaf: x509.Certificate, der: bytes, chain_len: int) -> dict:
    """What the details keep of the presented certificate (the path diagnosis and ARI read it)."""
    try:
        sans = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = [str(n.value) for n in sans if isinstance(n, (x509.DNSName, x509.IPAddress))]
    except (x509.ExtensionNotFound, ValueError):
        names = []
    try:
        issuer = leaf.issuer.rfc4514_string()[:MAX_TEXT]
    except ValueError:
        issuer = None
    return {
        "not_before": iso_utc(leaf.not_valid_before_utc),
        "not_after": iso_utc(leaf.not_valid_after_utc),
        "sha256": hashlib.sha256(der).hexdigest(),
        "serial": format(leaf.serial_number, "x"),
        "issuer": issuer,
        "san": [n[:MAX_TEXT] for n in names[:MAX_SANS]],
        "chain_len": chain_len,
    }


def _reason(exc: BaseException) -> str:
    return str(getattr(exc, "reason", None) or str(exc) or type(exc).__name__)[:MAX_TEXT]
