# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enrollment-token store abstraction.

Tokens are minted by the server's control plane (like today's provisioning
tokens) and consumed here. This module defines the Protocol + an in-memory store
for tests/dev; the production store is the DB-backed DbTokenStore in app/db.py,
selected via DATABASE_URL in main.build_issuer.
"""

from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EnrollmentGrant:
    """What a consumed token entitles the bearer to: a fixed identity + scope,
    dictated by the server, never by the client's CSR."""

    subject_id: str
    scope: str  # "tunnel" | "access" | "internal"
    browser: bool = False  # browser leaves get the long lifetime (D5)


class TokenStore(Protocol):
    def consume(self, token: str) -> EnrollmentGrant | None:
        """One-time consume: return the grant and invalidate the token so it cannot
        be reused, or None if the token is unknown/expired/already consumed."""
        ...

    def is_active(self, subject_id: str, scope: str) -> bool:
        """Renewal gate: False once an identity is deprovisioned (fast cut-off
        without CRL, ADR 0001 §3.4)."""
        ...


@dataclass
class _Entry:
    grant: EnrollmentGrant
    expires_at: datetime.datetime


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

    def is_active(self, subject_id: str, scope: str) -> bool:
        return (subject_id, scope) not in self._deprovisioned
