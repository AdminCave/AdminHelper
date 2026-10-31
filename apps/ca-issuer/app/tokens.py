# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enrollment-token store abstraction.

Tokens are minted by the server's control plane (like today's provisioning
tokens) and consumed here. This module defines the Protocol + an in-memory store
for tests/dev; the production store is the DB-backed DbTokenStore in app/db.py,
selected via DATABASE_URL in main.build_issuer.

The store also keeps the certificate register (R-0224): every leaf issued at
enrollment is recorded by its fingerprint on a new device line, and ``replaces``
revokes the line of the certificate it names. A renewal stays on the line of the
certificate it renews, and only a certificate the register admits is renewed.
"""

from __future__ import annotations

import datetime
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from cryptography import x509
from cryptography.hazmat.primitives import hashes


@dataclass(frozen=True)
class EnrollmentGrant:
    """What a consumed token entitles the bearer to: a fixed identity + scope,
    dictated by the server, never by the client's CSR."""

    subject_id: str
    scope: str  # "tunnel" | "access" | "internal"
    browser: bool = False  # browser leaves get the long lifetime (D5)


@dataclass(frozen=True)
class CertRecord:
    """An issued leaf as the register keeps it."""

    fingerprint: str  # SHA-256 over DER, lowercase hex (the hash of RFC 8705 x5t#S256)
    serial: str  # hex; up to 159 bits
    not_before: datetime.datetime  # naive UTC, like the server's columns (F7)
    not_after: datetime.datetime

    @classmethod
    def of(cls, leaf: x509.Certificate) -> CertRecord:
        return cls(
            fingerprint=leaf.fingerprint(hashes.SHA256()).hex(),
            serial=format(leaf.serial_number, "x"),
            not_before=leaf.not_valid_before_utc.replace(tzinfo=None),
            not_after=leaf.not_valid_after_utc.replace(tzinfo=None),
        )


@dataclass(frozen=True)
class LineInfo:
    """The device line a recorded certificate belongs to."""

    line_id: str
    subject_id: str
    scope: str
    kind: str
    legacy: bool
    revoked_reason: str | None


# How long after the register was installed a certificate it never recorded (issued
# before it existed) is still taken over: the native lifetime, so every active device
# has renewed onto the register by then.
LEGACY_WINDOW = datetime.timedelta(days=90)


class RenewalRefused(Exception):
    """The register does not admit the certificate presented for renewal."""


def _now_naive() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def legacy_admitted(
    not_before: datetime.datetime,
    installed_at: datetime.datetime | None,
    now: datetime.datetime,
) -> bool:
    """Whether an unrecorded certificate may be taken over: issued before the
    register existed, while the transition still runs. One issued after it cannot
    be genuine, since every issuance since then is recorded. Without an install
    time (no state row) nothing is taken over."""
    if installed_at is None:
        return False
    return not_before < installed_at and now < installed_at + LEGACY_WINDOW


def kind_of(grant: EnrollmentGrant) -> str:
    """The kind of device a grant enrolls: agents live under the tunnel scope, a
    browser grant is a .p12 export, anything else is a desktop."""
    if grant.scope == "tunnel":
        return "agent"
    return "browser" if grant.browser else "desktop"


# Signs the leaf for a consumed grant and returns it with the response body.
Signer = Callable[[EnrollmentGrant], tuple[x509.Certificate, dict[str, str]]]
# Signs the successor of a renewed certificate, for the kind of its device line.
RenewSigner = Callable[[str], tuple[x509.Certificate, dict[str, str]]]


class TokenStore(Protocol):
    def consume(self, token: str) -> EnrollmentGrant | None:
        """One-time consume: return the grant and invalidate the token so it cannot
        be reused, or None if the token is unknown/expired/already consumed."""
        ...

    def enroll(
        self, token: str, sign: Signer, replaces: str | None = None
    ) -> dict[str, str] | None:
        """Consume the token, sign, and record the leaf on a new device line, all in
        one step; ``replaces`` (a fingerprint) revokes that certificate's line when
        it belongs to the grant's subject and scope, and does nothing otherwise.
        None if the token is not usable, also when it was minted at or before the
        revocation of its identity (R-0306). If ``sign`` raises, the token stays
        unspent and nothing is recorded."""
        ...

    def renew(
        self,
        current: CertRecord,
        subject_id: str,
        scope: str,
        legacy_kind: str,
        sign: RenewSigner,
    ) -> dict[str, str]:
        """Renew a verified certificate onto its own line. Raises RenewalRefused when
        its identity was revoked at or after its notBefore, when its line is revoked,
        or when it is not recorded and not taken over (see ``legacy_admitted``; a
        taken-over certificate opens a ``legacy`` line of ``legacy_kind``)."""
        ...

    def is_active(
        self, subject_id: str, scope: str, not_before: datetime.datetime | None = None
    ) -> bool:
        """Revocation check: False for a certificate issued (``not_before``, naive UTC)
        at or before the identity was deprovisioned — the fast cut-off without CRL,
        ADR 0001 §3.4. Without ``not_before`` any deprovisioning counts."""
        ...


@dataclass
class _Entry:
    grant: EnrollmentGrant
    expires_at: datetime.datetime
    minted_at: datetime.datetime  # naive UTC, like the server's column


@dataclass
class _Line:
    subject_id: str
    scope: str
    kind: str
    legacy: bool = False
    revoked_reason: str | None = None


class InMemoryTokenStore:
    """For tests/dev. Not thread-safe enough for production — the real store is
    the DB-backed one (increment 4), which consumes via a conditional UPDATE."""

    def __init__(self, installed_at: datetime.datetime | None = None) -> None:
        # FastAPI runs sync-def endpoints in a threadpool, so two parallel /enroll requests with
        # the same token could both pass the used-check before either marked it used. Guard consume
        # with a lock and pop the entry atomically — that makes it truly one-time AND stops _tokens
        # from growing unbounded (consumed/expired entries are removed, not just flagged) (4.87).
        self._lock = threading.Lock()
        self._tokens: dict[str, _Entry] = {}
        self._deprovisioned: dict[tuple[str, str], datetime.datetime] = {}
        self._lines: dict[str, _Line] = {}
        self._certs: dict[str, str] = {}  # fingerprint -> line id
        # When the register "was installed": a fresh store has recorded nothing before.
        self.installed_at = installed_at or _now_naive()

    def mint(
        self,
        token: str,
        grant: EnrollmentGrant,
        ttl: datetime.timedelta = datetime.timedelta(minutes=15),
    ) -> None:
        self._tokens[token] = _Entry(
            grant=grant,
            expires_at=datetime.datetime.now(datetime.timezone.utc) + ttl,
            minted_at=_now_naive(),
        )

    def deprovision(self, subject_id: str, scope: str, at: datetime.datetime | None = None) -> None:
        """Revoke the identity as of ``at`` (naive UTC, default now)."""
        self._deprovisioned[(subject_id, scope)] = at or _now_naive()

    def consume(self, token: str) -> EnrollmentGrant | None:
        with self._lock:
            entry = self._tokens.pop(token, None)  # atomic one-time consume; also frees the entry
        if entry is None:
            return None
        if datetime.datetime.now(datetime.timezone.utc) >= entry.expires_at:
            return None
        return entry.grant

    def enroll(
        self, token: str, sign: Signer, replaces: str | None = None
    ) -> dict[str, str] | None:
        with self._lock:
            entry = self._tokens.pop(token, None)
        if entry is None or datetime.datetime.now(datetime.timezone.utc) >= entry.expires_at:
            return None
        grant = entry.grant
        with self._lock:
            if not self._active(grant.subject_id, grant.scope, entry.minted_at):
                return None  # minted at or before the revocation of its identity
        try:
            leaf, response = sign(grant)
        except Exception:
            with self._lock:
                self._tokens.setdefault(token, entry)  # a failed signing spends nothing
            raise
        record = CertRecord.of(leaf)
        with self._lock:
            line_id = str(uuid.uuid4())
            self._lines[line_id] = _Line(grant.subject_id, grant.scope, kind_of(grant))
            self._certs[record.fingerprint] = line_id
            replaced = self._lines.get(self._certs.get(replaces, "")) if replaces else None
            if (
                replaced is not None
                and (replaced.subject_id, replaced.scope) == (grant.subject_id, grant.scope)
                and replaced.revoked_reason is None
            ):
                replaced.revoked_reason = "replaced"
        return response

    def line_of(self, fingerprint: str) -> LineInfo | None:
        """The line of a recorded certificate, or None if it is not recorded."""
        with self._lock:
            line_id = self._certs.get(fingerprint)
            line = self._lines.get(line_id) if line_id else None
            if line is None:
                return None
            return LineInfo(
                line_id, line.subject_id, line.scope, line.kind, line.legacy, line.revoked_reason
            )

    def renew(
        self,
        current: CertRecord,
        subject_id: str,
        scope: str,
        legacy_kind: str,
        sign: RenewSigner,
    ) -> dict[str, str]:
        with self._lock:
            if not self._active(subject_id, scope, current.not_before):
                raise RenewalRefused("identity is deprovisioned")
            line_id = self._certs.get(current.fingerprint)
            taken_over = None
            if line_id is None:
                if not legacy_admitted(current.not_before, self.installed_at, _now_naive()):
                    raise RenewalRefused("certificate is not in the register")
                line_id = str(uuid.uuid4())
                taken_over = _Line(subject_id, scope, legacy_kind, legacy=True)
            line = taken_over or self._lines[line_id]
            if line.revoked_reason is not None or (line.subject_id, line.scope) != (
                subject_id,
                scope,
            ):
                raise RenewalRefused("the device line is revoked")
        leaf, response = sign(line.kind)
        with self._lock:
            # Once more after signing: a deprovisioning that came in meanwhile wins.
            if not self._active(subject_id, scope, current.not_before):
                raise RenewalRefused("identity is deprovisioned")
            if taken_over is not None:
                # The take-over is recorded only with its successor, as the DbTokenStore
                # does in one transaction; of two at once, the later one is refused.
                if current.fingerprint in self._certs:
                    raise RenewalRefused("recorded concurrently, retry the renewal")
                self._lines[line_id] = taken_over
                self._certs[current.fingerprint] = line_id
            self._certs[CertRecord.of(leaf).fingerprint] = line_id
        return response

    def _active(self, subject_id: str, scope: str, not_before: datetime.datetime | None) -> bool:
        revoked_at = self._deprovisioned.get((subject_id, scope))
        if revoked_at is None:
            return True
        return not_before is not None and not_before > revoked_at

    def is_active(
        self, subject_id: str, scope: str, not_before: datetime.datetime | None = None
    ) -> bool:
        with self._lock:
            return self._active(subject_id, scope, not_before)
