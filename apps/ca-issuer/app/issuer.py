# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Issuance orchestration: token → enroll, verified cert → renew.

The issuer is its own gatekeeper (ADR 0001 §3.3): /enroll authorizes via a
one-time token, /renew via the gateway-verified current cert. Neither the
client's CSR nor the calling server can widen identity, scope or lifetime.
"""

from __future__ import annotations

import logging

from cryptography import x509

from app import pki
from app.storage import Intermediate
from app.tokens import EnrollmentGrant, TokenStore

logger = logging.getLogger("ca-issuer.issuer")


class IssuanceError(Exception):
    """Raised when issuance is refused (bad token, deprovisioned, bad input)."""


def _leaf_days(grant: EnrollmentGrant) -> int:
    return pki.LEAF_DAYS_BROWSER if grant.browser else pki.LEAF_DAYS_NATIVE


class Issuer:
    def __init__(self, intermediates: dict[str, Intermediate], tokens: TokenStore) -> None:
        self._inter = intermediates
        self._tokens = tokens

    def _intermediate(self, scope: str) -> Intermediate:
        inter = self._inter.get(scope)
        if inter is None:
            raise IssuanceError(f"Unbekannter Scope '{scope}'")
        return inter

    def _sign(self, csr: x509.CertificateSigningRequest, spec: pki.LeafSpec) -> dict[str, str]:
        inter = self._intermediate(spec.scope)
        leaf = pki.sign_leaf(csr, inter.cert, inter.key, spec)
        leaf_pem = pki.cert_to_pem(leaf)
        return {
            "cert": leaf_pem.decode(),
            # fullchain = leaf + intermediate (what a client presents)
            "fullchain": (leaf_pem + pki.cert_to_pem(inter.cert)).decode(),
            # trust bundle = intermediate + root (what a client pins/validates against)
            "chain": inter.chain.decode(),
        }

    def enroll(self, token: str, csr_pem: bytes) -> dict[str, str]:
        grant = self._tokens.consume(token)
        if grant is None:
            raise IssuanceError("Ungültiger, abgelaufener oder bereits verwendeter Token")
        try:
            csr = x509.load_pem_x509_csr(csr_pem)
        except ValueError as exc:
            raise IssuanceError(f"Ungültige CSR: {exc}") from exc

        spec = pki.LeafSpec(
            lifetime_days=_leaf_days(grant),
            client_auth=True,
            server_auth=False,
            subject_cn=grant.subject_id,  # identity from the grant, NOT the CSR
            scope=grant.scope,
        )
        logger.info(
            "Enroll: %s (scope=%s, browser=%s)", grant.subject_id, grant.scope, grant.browser
        )
        return self._sign(csr, spec)

    def renew(self, verified_cert_pem: bytes, csr_pem: bytes) -> dict[str, str]:
        try:
            current = x509.load_pem_x509_certificate(verified_cert_pem)
        except ValueError as exc:
            raise IssuanceError(f"Vorgelegtes Cert nicht lesbar: {exc}") from exc

        cn, scope = pki.read_identity(current)
        if not cn or not scope:
            raise IssuanceError("Vorgelegtes Cert trägt keine Identität/Scope")
        if not self._tokens.is_active(cn, scope):
            raise IssuanceError("Identität ist deprovisioniert")

        try:
            csr = x509.load_pem_x509_csr(csr_pem)
        except ValueError as exc:
            raise IssuanceError(f"Ungültige CSR: {exc}") from exc

        # Preserve the original lifetime span (browser 365d renews to 365d,
        # native 90d to 90d) — no need to store the audience separately.
        span = current.not_valid_after_utc - current.not_valid_before_utc
        spec = pki.LeafSpec(
            lifetime_days=max(1, span.days),
            client_auth=True,
            server_auth=False,
            subject_cn=cn,
            scope=scope,
        )
        logger.info("Renew: %s (scope=%s, %dd)", cn, scope, spec.lifetime_days)
        return self._sign(csr, spec)
