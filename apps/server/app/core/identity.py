# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""mTLS client identity from the gateway (ADR 0001 §3.2, Phase A / A3).

The gateway (nginx) terminates TLS + mTLS and forwards the verified client cert
as headers. uvicorn cannot see the cert itself (V1), so the app reads identity
from those headers — trusted ONLY because the server has no host port and is
reachable solely through the gateway, which strips any client-supplied
``X-Client-*`` headers and sets them from the real, verified cert.

Scopes map to the PKI intermediates (ADR 0001 §3.1): ``access`` = humans
(desktop / browser / extension), ``tunnel`` = agents (they live under the tunnel
intermediate). The scope is carried in the cert's OU, set by the ca-issuer from
the enrollment grant — a client cannot widen it via its CSR.

Rollout (ADR 0002): ``require_scope`` is **permissive** by default — a missing or
mismatched scope is logged but the request proceeds, so the data plane stays
usable before clients have certs (A3–A7). A8 sets ``MTLS_ENFORCE=true`` to reject.
"""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass

from cryptography import x509
from cryptography.x509.oid import NameOID
from fastapi import Depends, HTTPException, Request, status

from app.core import config

logger = logging.getLogger("adminhelper.identity")

# Cert OU values (the enrollment scope). Centralized so the human/agent split is
# defined in exactly one place (A4 enrolls agents under SCOPE_AGENT).
SCOPE_ACCESS = "access"  # humans: desktop / browser / extension
SCOPE_AGENT = "tunnel"  # agents (under the tunnel intermediate, ADR 0001 §3.1)

# Gateway headers (lowercased). nginx sets these from the verified cert; the
# enroll plane strips them entirely. Mirrors what the ca-issuer reads on /renew.
_H_VERIFY = "x-client-verify"
_H_CERT = "x-client-cert"  # URL-escaped PEM ($ssl_client_escaped_cert)


@dataclass(frozen=True)
class ClientIdentity:
    """The verified mTLS identity, or an unverified placeholder when no
    SUCCESS-verified cert was presented (the normal case during the rollout)."""

    verified: bool
    cn: str | None = None
    scope: str | None = None

    def __bool__(self) -> bool:
        return self.verified


_UNVERIFIED = ClientIdentity(verified=False)


def _first(cert: x509.Certificate, oid: x509.ObjectIdentifier) -> str | None:
    attrs = cert.subject.get_attributes_for_oid(oid)
    return attrs[0].value if attrs else None


def get_client_identity(request: Request) -> ClientIdentity:
    """Parse the gateway-forwarded client identity from the verified cert.

    The cert PEM is the authoritative source (not the DN header), so the scope is
    read the same way the ca-issuer reads it on renewal. Returns the unverified
    placeholder whenever the gateway did not report a SUCCESS-verified cert."""
    if request.headers.get(_H_VERIFY, "").upper() != "SUCCESS":
        return _UNVERIFIED
    escaped = request.headers.get(_H_CERT, "")
    if not escaped:
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
    )


def require_scope(*allowed: str):
    """Dependency factory: require the client cert to carry one of ``allowed``
    scopes. Dual-use routes pass several (e.g. agent + admin read the same config).

    Permissive (default): a missing/mismatched scope is logged but the request
    proceeds — only a *wrong-scope* cert warns; the expected "no cert yet" case
    stays at debug so the rollout doesn't spam logs. Enforced (``MTLS_ENFORCE``,
    A8): a mismatch returns 403."""
    allowed_set = frozenset(allowed)

    def dependency(
        request: Request,
        identity: ClientIdentity = Depends(get_client_identity),
    ) -> ClientIdentity:
        if identity.verified and identity.scope in allowed_set:
            return identity

        if config.MTLS_ENFORCE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Kein gültiges Client-Zertifikat mit passendem Scope",
            )

        wanted = "/".join(sorted(allowed_set))
        if identity.verified:
            logger.warning(
                "mTLS permissiv: %s %s erwartet Scope %s, Cert hat '%s' (CN=%s) — erlaubt",
                request.method,
                request.url.path,
                wanted,
                identity.scope,
                identity.cn,
            )
        else:
            logger.debug(
                "mTLS permissiv: %s %s ohne verifiziertes Client-Cert (Scope %s) — erlaubt",
                request.method,
                request.url.path,
                wanted,
            )
        return identity

    return dependency
