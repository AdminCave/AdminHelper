# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enrollment-token minting, shared by the HTTP API and the management CLI.

The token is the access gate for certless enrollment (ADR 0001 §3.3 / ADR 0003):
single-use, hashed at rest with the same SHA-256 the ca-issuer consumes by, and
the identity (the cert CN) is fixed to ``subject_id`` here — never taken from the
client's CSR."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy.orm import Session

from app.core.auth import generate_api_key, hash_api_key
from app.core.time import utcnow_naive
from app.modules.enrollment.models import EnrollmentToken

# Default window: long enough to enroll right after login, short enough to limit
# exposure of the single-use grant. The install-time bootstrap passes a longer
# ttl (the operator needs time to paste the token into the desktop).
DEFAULT_TTL = datetime.timedelta(minutes=10)


def mint_enrollment_token(
    db: Session,
    subject_id: str,
    scope: str,
    *,
    browser: bool = False,
    ttl: datetime.timedelta = DEFAULT_TTL,
) -> str:
    """Persist a one-time enrollment token for ``subject_id``/``scope`` and return
    the raw (un-hashed) token to hand to the client. Commits the row."""
    raw_token = generate_api_key()
    db.add(
        EnrollmentToken(
            id=str(uuid.uuid4()),
            hashed_token=hash_api_key(raw_token),
            subject_id=subject_id,
            scope=scope,
            browser=browser,
            expires_at=utcnow_naive() + ttl,
        )
    )
    db.commit()
    return raw_token
