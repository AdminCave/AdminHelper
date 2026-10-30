# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""mTLS client identity from the gateway (ADR 0001 §3.2, Phase A / A3).

The gateway (nginx) terminates TLS + mTLS and forwards the verified client cert
as headers. uvicorn cannot see the cert itself (V1), so the app reads identity
from those headers — trusted ONLY because the server takes them from the gateway
alone: the request's direct peer has to be an address of the compose service
``gateway`` (``_from_gateway``). The gateway strips any client-supplied
``X-Client-*`` headers and sets them from the real, verified cert. The missing
host port keeps out only the outside: the other services of the compose network
reach the server as well, and their headers count as no cert.

Scopes map to the PKI intermediates (ADR 0001 §3.1): ``access`` = humans
(desktop / browser), ``tunnel`` = agents (they live under the tunnel
intermediate). The scope is carried in the cert's OU, set by the ca-issuer from
the enrollment grant — a client cannot widen it via its CSR.

Enforcement (ADR 0002, A8): ``require_scope`` is **enforced** by default
(``MTLS_ENFORCE`` unset or ``true``, ``app.core.config``) — a missing or
mismatched scope gets a 403. ``MTLS_ENFORCE=false`` is the permissive mode of the
rollout (A3–A7), kept only for a manual first bootstrap: the mismatch is logged
and the request proceeds.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core import config
from app.core.database import get_db
from app.core.errors import CodedHTTPException
from app.core.middleware import _NameResolver

logger = logging.getLogger("adminhelper.identity")

# Cert OU values (the enrollment scope). Centralized so the human/agent split is
# defined in exactly one place (A4 enrolls agents under SCOPE_AGENT).
SCOPE_ACCESS = "access"  # humans: desktop / browser
SCOPE_AGENT = "tunnel"  # agents (under the tunnel intermediate, ADR 0001 §3.1)

# Gateway headers (lowercased). nginx sets these from the verified cert; the
# enroll plane strips them entirely. Mirrors what the ca-issuer reads on /renew.
_H_VERIFY = "x-client-verify"
_H_CERT = "x-client-cert"  # URL-escaped PEM ($ssl_client_escaped_cert)

# The compose service whose requests may carry those headers (_from_gateway). A list
# of its own, not TRUSTED_PROXIES: an entry there vouches for the client address a
# proxy forwards, not for a client certificate.
_GATEWAY_NAMES = ("gateway",)
_GATEWAY = _NameResolver(list(_GATEWAY_NAMES), label="mTLS identity", thread_name="gateway-names")
# A recreated gateway (an update) comes back with a new address: a request from an
# unknown peer waits this long for the fresh lookup that has_address starts.
_GATEWAY_WAIT = 1.0
_IGNORED_LOG_INTERVAL = 60.0  # one warning per peer and minute
_ignored_logged: dict[str | None, float] = {}
_ignored_lock = threading.Lock()


@dataclass(frozen=True)
class ClientIdentity:
    """The verified mTLS identity, or an unverified placeholder when no
    SUCCESS-verified cert was presented (the normal case during the rollout)."""

    verified: bool
    cn: str | None = None
    scope: str | None = None
    not_before: datetime | None = None  # naive UTC, like the register's columns (F7)
    # What the certificate register keys on and records (R-0224).
    fingerprint: str | None = None  # SHA-256 over DER, lowercase hex
    serial: str | None = None  # hex
    not_after: datetime | None = None  # naive UTC

    def __bool__(self) -> bool:
        return self.verified


_UNVERIFIED = ClientIdentity(verified=False)


def _first(cert: x509.Certificate, oid: x509.ObjectIdentifier) -> str | None:
    attrs = cert.subject.get_attributes_for_oid(oid)
    return attrs[0].value if attrs else None


def _from_gateway(request: Request) -> bool:
    """Whether the request's direct peer is the gateway, decided once per request
    like the register's answer in _refused: a request reads its identity several
    times (the scope guard, then the binding to the user), and a resolver that
    changes in between must neither split the answer nor make the request wait
    twice."""
    cached = getattr(request.state, "from_gateway", None)
    if cached is None:
        cached = _peer_is_gateway(request)
        request.state.from_gateway = cached
    return cached


def _peer_is_gateway(request: Request) -> bool:
    """Whether the direct peer is a current address of _GATEWAY_NAMES. If not, a
    warning names the peer, at most once a minute each. The peer is uvicorn's
    scope["client"], which it rewrites from X-Forwarded-For only for peers in
    FORWARDED_ALLOW_IPS (default the loopback addresses), so a forwarded header
    from another service cannot pose as the gateway."""
    peer = request.client.host if request.client else None
    if peer is not None and _GATEWAY.has_address(peer, wait=_GATEWAY_WAIT):
        return True
    now = time.monotonic()
    with _ignored_lock:
        last = _ignored_logged.get(peer)
        if last is not None and now - last < _IGNORED_LOG_INTERVAL:
            return False
        for seen, at in list(_ignored_logged.items()):
            if now - at >= _IGNORED_LOG_INTERVAL:
                del _ignored_logged[seen]
        _ignored_logged[peer] = now
    logger.warning(
        "mTLS: %s %r from %s carries client certificate headers but does not come "
        "from the gateway; they are ignored",
        request.method,
        request.url.path,
        peer or "an unknown peer",
    )
    return False


def get_client_identity(request: Request) -> ClientIdentity:
    """Parse the gateway-forwarded client identity from the verified cert.

    The cert PEM is the authoritative source (not the DN header), so the scope is
    read the same way the ca-issuer reads it on renewal. Returns the unverified
    placeholder whenever the gateway did not report a SUCCESS-verified cert, or
    the request does not come from the gateway. Only a request that reports one
    asks the resolver, so plain requests never wait on DNS; one from an unknown
    peer may wait up to _GATEWAY_WAIT. So this stays a sync function, which
    FastAPI runs in its threadpool, and its callers stay off the event loop."""
    if request.headers.get(_H_VERIFY, "").upper() != "SUCCESS":
        return _UNVERIFIED
    if not _from_gateway(request):
        return _UNVERIFIED
    escaped = request.headers.get(_H_CERT, "")
    # Cap the header before unquote()+parse: a very large forwarded value would otherwise burn
    # CPU/memory unbounded. A leaf PEM is well under 16 KiB (4.132).
    if not escaped or len(escaped) > 16384:
        return _UNVERIFIED
    try:
        pem = urllib.parse.unquote(escaped).encode()
        cert = x509.load_pem_x509_certificate(pem)
    except ValueError:
        logger.warning("Vom Gateway weitergereichtes Client-Cert nicht parsebar")
        return _UNVERIFIED
    return ClientIdentity(
        verified=True,
        cn=_first(cert, NameOID.COMMON_NAME),
        scope=_first(cert, NameOID.ORGANIZATIONAL_UNIT_NAME),
        not_before=cert.not_valid_before_utc.replace(tzinfo=None),
        fingerprint=cert.fingerprint(hashes.SHA256()).hex(),
        serial=format(cert.serial_number, "x"),
        not_after=cert.not_valid_after_utc.replace(tzinfo=None),
    )


# The 403 for a certificate of another user. A client branches on its code, the
# body's `code`; the detail keeps it as prefix for clients that still read the text.
# The prose may change, the code must not.
CERT_USER_MISMATCH_CODE = "ERR_CERT_USER_MISMATCH"
CERT_USER_MISMATCH = (
    f"{CERT_USER_MISMATCH_CODE}: The client certificate belongs to another user. Sign in as "
    "that user, or register this device for yourself."
)


# The 403 for an agent certificate on a route of another server (R-0283).
CERT_SERVER_MISMATCH_CODE = "ERR_CERT_SERVER_MISMATCH"
CERT_SERVER_MISMATCH = (
    f"{CERT_SERVER_MISMATCH_CODE}: The client certificate belongs to another server. "
    "Provision this host for the server it reports for."
)


# The 403 for a certificate the register refuses: revoked, or not recorded after the
# transition (R-0224). A client keys its hint off the code, as with CERT_USER_MISMATCH.
CERT_REVOKED_CODE = "ERR_CERT_REVOKED"
CERT_REVOKED = (
    f"{CERT_REVOKED_CODE}: This device certificate is no longer valid. Reset the device "
    "identity and register the device again."
)


# The 403 of an enforced request without a fitting client certificate.
_NO_CERT = "Kein gültiges Client-Zertifikat mit passendem Scope"


def require_cert_if_enforced(request: Request) -> None:
    """Enforced (``MTLS_ENFORCE``), the sign-in routes need a verified client certificate
    as every other route does (R-0900): login, refresh and bootstrap carry no scope guard,
    and require_cert_user lets a request without a certificate through. Permissive, nothing
    changes: the manual first bootstrap runs without one."""
    if config.MTLS_ENFORCE and not get_client_identity(request).verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_NO_CERT)


def require_cert_user(request: Request, username: str, db: Session) -> None:
    """Under mTLS the client certificate belongs to the signed-in user (R-0223): a
    verified identity must carry the access scope and ``username`` as its CN, or the
    request gets a 403. The certificate itself must be one the register admits
    (R-0224), or the 403 says so. Without a verified identity there is nothing to
    check. Callers apply it where a user comes from a JWT or credentials; an API key
    belongs to no user and is not bound."""
    identity = get_client_identity(request)
    if not identity.verified:
        return
    if _refused(request, db, identity):
        _deny_refused(request, identity)
    if identity.scope == SCOPE_ACCESS and identity.cn == username:
        return
    logger.warning(
        "mTLS: %s %r — Client-Cert CN=%s (scope=%s) gehört nicht zum Benutzer %s",
        request.method,
        request.url.path,
        identity.cn,
        identity.scope,
        username,
    )
    raise CodedHTTPException(status.HTTP_403_FORBIDDEN, CERT_USER_MISMATCH, CERT_USER_MISMATCH_CODE)


def require_cert_server(server_id: str, request: Request) -> None:
    """An agent certificate belongs to the server it was provisioned for (R-0283): on a
    route of one server (``server_id`` in the path), a verified identity of the agent
    scope must carry that server_id as its CN, or the request gets a 403, in both modes
    like the binding to the user. An access certificate (an admin) and a request without
    a verified identity are not this check's; the scope guard of the route decides."""
    identity = get_client_identity(request)
    if not identity.verified or identity.scope != SCOPE_AGENT or identity.cn == server_id:
        return
    logger.warning(
        "mTLS: %s %r — agent certificate CN=%s is not for server %s",
        request.method,
        request.url.path,
        identity.cn,
        server_id,
    )
    raise CodedHTTPException(
        status.HTTP_403_FORBIDDEN, CERT_SERVER_MISMATCH, CERT_SERVER_MISMATCH_CODE
    )


def _is_revoked(
    db: Session | None,
    cn: str | None,
    scope: str | None,
    not_before: datetime | None = None,
    identity: ClientIdentity | None = None,
) -> bool:
    """Whether the verified certificate is refused (ADR 0001 §3.4 lever 2 — the
    immediate data-plane cut-off, not waiting for cert expiry): a revocation of its
    CN and scope at or after its ``not_before``, and with the full ``identity`` the
    certificate register as well — its device line revoked, or not recorded once the
    transition is over (R-0224). ``db`` is the request session; it is None only in
    pure-logic unit tests, where there is no revocation to check."""
    if db is None or cn is None or scope is None:
        return False
    from app.modules.enrollment.models import admit_certificate, is_identity_revoked

    if identity is None:
        return is_identity_revoked(db, cn, scope, not_before)
    return not admit_certificate(
        db,
        cn=cn,
        scope=scope,
        fingerprint=identity.fingerprint,
        serial=identity.serial,
        not_before=identity.not_before,
        not_after=identity.not_after,
    )


def _refused(request: Request, db: Session, identity: ClientIdentity) -> bool:
    """The register's answer for this request's certificate, asked once per request:
    an access route runs require_scope and get_current_user, and both ask."""
    cached = getattr(request.state, "certificate_refused", None)
    if cached is None:
        cached = _is_revoked(
            db, identity.cn, identity.scope, not_before=identity.not_before, identity=identity
        )
        request.state.certificate_refused = cached
    return cached


def _deny_refused(request: Request, identity: ClientIdentity) -> None:
    logger.warning(
        "mTLS: %s %r — client certificate CN=%s (scope=%s) is revoked or not recorded",
        request.method,
        request.url.path,
        identity.cn,
        identity.scope,
    )
    raise CodedHTTPException(status.HTTP_403_FORBIDDEN, CERT_REVOKED, CERT_REVOKED_CODE)


def check_scope(
    request: Request, identity: ClientIdentity, db: Session, allowed: frozenset[str]
) -> ClientIdentity:
    """The check of require_scope on a session the caller holds: the SSE stream runs it on
    its short session, so no get_db session lives as long as the stream."""
    # Check the scope before the register query, and only a cert of a wanted scope asks the
    # register (5.27): enforced, a wrong-scope cert is rejected anyway; permissive, it grants
    # nothing here and the request rests on its other credentials, so the scope mismatch is
    # what gets logged.
    if identity.verified and identity.scope in allowed:
        if _refused(request, db, identity):
            _deny_refused(request, identity)
        return identity

    if config.MTLS_ENFORCE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_NO_CERT)

    wanted = "/".join(sorted(allowed))
    if identity.verified:
        logger.warning(
            "mTLS permissiv: %s %r erwartet Scope %s, Cert hat '%s' (CN=%s) — erlaubt",
            request.method,
            request.url.path,
            wanted,
            identity.scope,
            identity.cn,
        )
    else:
        logger.debug(
            "mTLS permissiv: %s %r ohne verifiziertes Client-Cert (Scope %s) — erlaubt",
            request.method,
            request.url.path,
            wanted,
        )
    return identity


def require_scope(*allowed: str):
    """Dependency factory: require the client cert to carry one of ``allowed``
    scopes and not be revoked. Dual-use routes pass several (e.g. agent + admin
    read the same config).

    Enforced (default, ``MTLS_ENFORCE``, A8): a missing/mismatched cert returns 403.
    Permissive (``MTLS_ENFORCE=false``): either is logged but the request proceeds —
    only a *wrong-scope* cert warns; the expected "no cert yet" case stays at debug so
    the rollout doesn't spam logs. A presented certificate the register refuses gets
    the 403 in both modes, like the binding to the user (R-0224)."""
    allowed_set = frozenset(allowed)

    def dependency(
        request: Request,
        identity: ClientIdentity = Depends(get_client_identity),
        db: Session = Depends(get_db),
    ) -> ClientIdentity:
        return check_scope(request, identity, db, allowed_set)

    return dependency
