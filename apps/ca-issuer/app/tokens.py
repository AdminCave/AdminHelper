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
revokes the line of the certificate it names.
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


def kind_of(grant: EnrollmentGrant) -> str:
    """The kind of device a grant enrolls: agents live under the tunnel scope, a
    browser grant is a .p12 export, anything else is a desktop."""
    if grant.scope == "tunnel":
        return "agent"
    return "browser" if grant.browser else "desktop"


# Signs the leaf for a consumed grant and returns it with the response body.
Signer = Callable[[EnrollmentGrant], tuple[x509.Certificate, dict[str, str]]]


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
        None if the token is not usable. If ``sign`` raises, the token stays
        unspent and nothing is recorded."""
        ...

    def is_active(self, subject_id: str, scope: str) -> bool:
        """Renewal gate: False once an identity is deprovisioned (fast cut-off
        without CRL, ADR 0001 §3.4)."""
        ...


@dataclass
class _Entry:
    grant: EnrollmentGrant
    expires_at: datetime.datetime


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

    def __init__(self) -> None:
        # FastAPI runs sync-def endpoints in a threadpool, so two parallel /enroll requests with
        # the same token could both pass the used-check before either marked it used. Guard consume
        # with a lock and pop the entry atomically — that makes it truly one-time AND stops _tokens
        # from growing unbounded (consumed/expired entries are removed, not just flagged) (4.87).
        self._lock = threading.Lock()
        self._tokens: dict[str, _Entry] = {}
        self._deprovisioned: set[tuple[str, str]] = set()
        self._lines: dict[str, _Line] = {}
        self._certs: dict[str, str] = {}  # fingerprint -> line id

    def mint(
        self,
        token: str,
        grant: EnrollmentGrant,
        ttl: datetime.timedelta = datetime.timedelta(minutes=15),
    ) -> None:
        self._tokens[token] = _Entry(
            grant=grant, expires_at=datetime.datetime.now(datetime.timezone.utc) + ttl
        )

    def deprovision(self, subject_id: str, scope: str) -> None:
        self._deprovisioned.add((subject_id, scope))

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

    def is_active(self, subject_id: str, scope: str) -> bool:
        return (subject_id, scope) not in self._deprovisioned
