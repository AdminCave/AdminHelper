# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Issuance orchestration: token → enroll, verified cert → renew.

The issuer is its own gatekeeper (ADR 0001 §3.3): /enroll authorizes via a
one-time token, /renew via the gateway-verified current cert. Neither the
client's CSR nor the calling server can widen identity, scope or lifetime.
"""

from __future__ import annotations

import datetime
import logging
import threading

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import ec

from app import pki
from app.storage import CLOCK_HINT, ROTATE_HINT, Intermediate
from app.tokens import CertRecord, EnrollmentGrant, RenewalRefused, TokenStore, kind_of

logger = logging.getLogger("ca-issuer.issuer")


class IssuanceError(Exception):
    """Raised when issuance is refused (bad token, deprovisioned, bad input)."""


class IssuerUnavailable(Exception):
    """Raised when the intermediate of a scope is expired or not yet valid: a fault of
    the service, not a refusal of the client, so deliberately no IssuanceError."""


def _leaf_days(grant: EnrollmentGrant) -> int:
    return pki.LEAF_DAYS_BROWSER if grant.browser else pki.LEAF_DAYS_NATIVE


class Issuer:
    def __init__(self, intermediates: dict[str, Intermediate], tokens: TokenStore) -> None:
        self._inter = intermediates
        self.tokens = tokens  # public: lifespan exposes it on app.state for minting/tests
        # The UTC day each scope last warned that its intermediate ends soon: once a day
        # is enough, however many leaves it signs (sync endpoints run in a threadpool).
        self._warned_on: dict[str, datetime.date] = {}
        self._warned_lock = threading.Lock()

    def _intermediate(self, scope: str) -> Intermediate:
        inter = self._inter.get(scope)
        if inter is None:
            raise IssuanceError(f"Unbekannter Scope '{scope}'")
        return inter

    def _verify_ca_signed(self, cert: x509.Certificate, scope: str) -> None:
        """Defense-in-depth: verify the presented cert was signed by the intermediate
        of its own scope and is time-valid, instead of trusting the gateway's
        x-client-verify: SUCCESS header alone. The `pki` compose network now fences the
        issuer to the gateway (1.1), but this stays a second line: should that boundary
        ever regress, a reachable container still must not be able to POST a self-made
        cert and renew any identity (3.3). Only the intermediates of that scope count:
        the issuer always signs a leaf of scope X with intermediate X, so a leaf whose
        OU names another scope than its signer is not one of ours (R-0224). Besides the
        current one these are the scope's retired intermediates while they are valid
        themselves, so a leaf issued before a rotation still renews (R-0667); its
        successor is signed by the current one."""
        now = pki._now()
        if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
            raise IssuanceError("Vorgelegtes Cert ist abgelaufen oder noch nicht gültig")
        inter = self._inter.get(scope)
        if inter is None:
            raise IssuanceError("presented certificate carries an unknown scope")
        # The loader leaves out retired intermediates past their end at boot; this
        # drops one that ends while the issuer runs.
        valid_retired = [
            old
            for old in inter.retired
            if old.not_valid_before_utc <= now <= old.not_valid_after_utc
        ]
        failure: Exception | None = None
        for signer in (inter.cert, *valid_retired):
            try:
                signer.public_key().verify(
                    cert.signature,
                    cert.tbs_certificate_bytes,
                    ec.ECDSA(cert.signature_hash_algorithm),
                )
                return
            except (InvalidSignature, TypeError, ValueError, UnsupportedAlgorithm) as exc:
                # Any non-ECDSA or malformed presented cert (e.g. an Ed25519 leaf whose
                # signature_hash_algorithm is None, an RSA key, or a signature algorithm
                # cryptography does not know) fails to verify against
                # our ECDSA intermediate — it is a forgery and must be rejected cleanly
                # here, never bubble up as a 500 at the issuer.
                failure = failure or exc
        raise IssuanceError(
            "presented certificate is not signed by the intermediate of its scope"
        ) from failure

    def _sign(
        self, csr: x509.CertificateSigningRequest, spec: pki.LeafSpec
    ) -> tuple[x509.Certificate, dict[str, str]]:
        """The signed leaf (for the register) and the response body."""
        inter = self._intermediate(spec.scope)
        try:
            leaf = pki.sign_leaf(csr, inter.cert, inter.key, spec)
        except pki.IssuerNotValid as exc:
            # Only an expired intermediate is cured by a rotation (see storage.CLOCK_HINT).
            if pki._now() >= inter.cert.not_valid_after_utc:
                state, hint = "expired", ROTATE_HINT
            else:
                state, hint = "not yet valid", CLOCK_HINT
            logger.error("intermediate %r cannot sign: %s; %s", inter.scope, exc, hint)
            raise IssuerUnavailable(
                f"the issuing intermediate certificate of scope '{inter.scope}' is {state}; "
                f"see the ca-issuer log and {hint}"
            ) from exc
        self._warn_if_ending(inter)
        leaf_pem = pki.cert_to_pem(leaf)
        return leaf, {
            "cert": leaf_pem.decode(),
            # fullchain = leaf + intermediate (what a client presents)
            "fullchain": (leaf_pem + pki.cert_to_pem(inter.cert)).decode(),
            # trust bundle = intermediate + root (what a client pins/validates against)
            "chain": inter.chain.decode(),
        }

    def _warn_if_ending(self, inter: Intermediate) -> None:
        now = pki._now()
        left = pki.days_left(inter.cert, now)
        if left >= pki.EXPIRY_WARN_DAYS:
            return
        with self._warned_lock:
            if self._warned_on.get(inter.scope) == now.date():
                return
            self._warned_on[inter.scope] = now.date()
        logger.warning(
            "intermediate %r expires on %s (%d days left); %s",
            inter.scope,
            inter.cert.not_valid_after_utc.isoformat(),
            left,
            ROTATE_HINT,
        )

    @staticmethod
    def _load_csr(csr_pem: bytes) -> x509.CertificateSigningRequest:
        """Parse and signature-check a CSR, mapping any client-input error to IssuanceError
        (a 4xx) instead of letting a malformed CSR or a bad signature surface as a 500 — the
        latter because sign_leaf raises a bare ValueError on an invalid signature (4.15)."""
        try:
            csr = x509.load_pem_x509_csr(csr_pem)
        except ValueError as exc:
            raise IssuanceError(f"Ungültige CSR: {exc}") from exc
        if not csr.is_signature_valid:
            raise IssuanceError("CSR-Signatur ist ungültig")
        return csr

    def enroll(self, token: str, csr_pem: bytes, replaces: str | None = None) -> dict[str, str]:
        """``replaces`` is the fingerprint of the certificate this device held before;
        its line is revoked when it belongs to the same subject and scope (R-0224)."""
        # Validate the CSR fully (parse + signature) BEFORE consuming the one-time token: a
        # client-side format or signature error (truncated PEM, corrupted CSR) must not burn the
        # token, or the retry with a corrected CSR fails as "already used" and an operator has to
        # mint a fresh token by hand (4.16).
        csr = self._load_csr(csr_pem)

        def sign(grant: EnrollmentGrant) -> tuple[x509.Certificate, dict[str, str]]:
            spec = pki.LeafSpec(
                lifetime_days=_leaf_days(grant),
                client_auth=True,
                server_auth=False,
                subject_cn=grant.subject_id,  # identity from the grant, NOT the CSR
                scope=grant.scope,
            )
            logger.info(
                "Enroll: %s (scope=%s, browser=%s, replaces=%s)",
                grant.subject_id,
                grant.scope,
                grant.browser,
                bool(replaces),
            )
            return self._sign(csr, spec)

        issued = self.tokens.enroll(token, sign, replaces)
        if issued is None:
            raise IssuanceError("Ungültiger, abgelaufener oder bereits verwendeter Token")
        return issued

    def renew(self, verified_cert_pem: bytes, csr_pem: bytes) -> dict[str, str]:
        try:
            current = x509.load_pem_x509_certificate(verified_cert_pem)
        except ValueError as exc:
            raise IssuanceError(f"Vorgelegtes Cert nicht lesbar: {exc}") from exc

        try:
            cn, scope = pki.read_identity(current)
        except ValueError as exc:
            # The subject is parsed lazily: a malformed one fails here, a 4xx like any forgery.
            raise IssuanceError("presented certificate has an unreadable subject") from exc
        if not cn or not scope:
            raise IssuanceError("Vorgelegtes Cert trägt keine Identität/Scope")
        # Never trust the gateway header alone: the issuer holds the intermediates,
        # so it verifies the presented cert against the one of its scope itself (3.3).
        self._verify_ca_signed(current, scope)

        csr = self._load_csr(csr_pem)

        # Preserve the audience (browser vs native — inferred from the original
        # span, since it isn't stored in the cert) and renew at the CURRENT policy
        # for it, not at the old span: sign_leaf cuts a leaf short before its
        # intermediate's end, and that cut must not pass to every successor; a
        # lowered LEAF_DAYS_* likewise reaches renewals instead of every legacy
        # identity renewing at its original span forever.
        span_days = max(1, (current.not_valid_after_utc - current.not_valid_before_utc).days)
        audience_max = (
            pki.LEAF_DAYS_BROWSER if span_days > pki.LEAF_DAYS_NATIVE else pki.LEAF_DAYS_NATIVE
        )
        spec = pki.LeafSpec(
            lifetime_days=audience_max,
            client_auth=True,
            server_auth=False,
            subject_cn=cn,
            scope=scope,
        )

        def sign() -> tuple[x509.Certificate, dict[str, str]]:
            logger.info("Renew: %s (scope=%s, %dd)", cn, scope, spec.lifetime_days)
            return self._sign(csr, spec)

        # A certificate the register never recorded gets the kind its span tells.
        legacy_kind = kind_of(EnrollmentGrant(cn, scope, browser=span_days > pki.LEAF_DAYS_NATIVE))
        try:
            return self.tokens.renew(CertRecord.of(current), cn, scope, legacy_kind, sign)
        except RenewalRefused as exc:
            raise IssuanceError(str(exc)) from exc
