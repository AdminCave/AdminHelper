# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enrollment-token minting for human clients (ADR 0001 §3.3 / A5).

The desktop (and later the browser) authenticates with its JWT and mints a
one-time, access-scoped enrollment token, then redeems it at the ca-issuer to
get its mTLS client cert. This is the human counterpart to provision/activate
(which mints a tunnel-scoped token for agents). Deliberately JWT-gated, NOT
cert-gated: the client has no cert yet — this is its bootstrap door.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin, get_current_user
from app.core.config import ENROLL_PORT
from app.core.database import get_db
from app.core.identity import SCOPE_ACCESS
from app.modules.enrollment.service import mint_enrollment_token
from app.modules.users.models import User

router = APIRouter(prefix="/api/enrollment", tags=["enrollment"])


def _mint_token(db: Session, subject_id: str, browser: bool) -> dict:
    """Persist a one-time access-scoped enrollment token for ``subject_id`` and
    return the redeemable grant. Identity (the cert CN) is issuer-dictated to
    ``subject_id``, never taken from the client's CSR; hashed at rest with the
    same SHA-256 the ca-issuer consumes by. ``browser=true`` flags a long-lived
    leaf (D5): the browser cannot auto-renew, so it gets a long cert + manual
    re-import; the desktop exports it as a PKCS12 for the browser cert store (A5c)."""
    raw_token = mint_enrollment_token(db, subject_id, SCOPE_ACCESS, browser=browser)
    return {
        "token": raw_token,
        "subjectId": subject_id,
        "scope": SCOPE_ACCESS,
        "browser": browser,
        # The client derives the enroll host from its own (already-trusted) server
        # URL + this port (the gateway's certless enroll plane).
        "enrollPort": ENROLL_PORT,
    }


@router.post("/token")
def mint_self_enrollment_token(
    browser: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mint a one-time access-scoped enrollment token for the logged-in user.

    The self-service door: the caller authenticates with its JWT and mints a
    token for *its own* identity, then redeems it at the ca-issuer."""
    return _mint_token(db, current_user.username, browser)


class EnrollmentTokenForRequest(BaseModel):
    username: str
    browser: bool = False


@router.post("/token/for")
def mint_enrollment_token_for(
    data: EnrollmentTokenForRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Admin-mint a one-time enrollment token FOR another (existing) user.

    The decoupled-enrollment door (ADR 0003): under enforced mTLS a brand-new
    human cannot reach the cert-gated :443 to mint its own token, so an admin
    (who already holds a cert) mints one here and hands it over out-of-band. The
    new user redeems it at the certless :8444 enroll plane, gets a cert with its
    *own* username as CN (issuer-dictated), then logs in on :443. Admin-only; the
    target user must already exist."""
    target = db.query(User).filter(User.username == data.username).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Unbekannter Benutzer")
    return _mint_token(db, target.username, data.browser)
