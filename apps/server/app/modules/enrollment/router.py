# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enrollment-token minting for human clients (ADR 0001 §3.3 / A5).

The desktop (and later the browser) authenticates with its JWT and mints a
one-time, access-scoped enrollment token, then redeems it at the ca-issuer to
get its mTLS client cert. This is the human counterpart to provision/activate
(which mints a tunnel-scoped token for agents). JWT-gated, no cert guard of its
own; but under MTLS_ENFORCE=true (the default) the gateway lets only a device
with a valid client cert reach :443, so the self-mint registers a further own
device; a device without a cert registers with a token from /token/for (ADR 0003).
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin, get_current_user
from app.core.bounds import RequestModel
from app.core.config import ENROLL_PORT
from app.core.database import get_db
from app.core.identity import SCOPE_ACCESS, ClientIdentity, require_scope
from app.core.middleware import resolve_client_ip
from app.core.request_context import Actor, actor_from_request
from app.core.time import iso_utc
from app.modules.audit import service as audit
from app.modules.enrollment.models import line_of, revoke_line
from app.modules.enrollment.schemas import EnrollmentGrantOut
from app.modules.enrollment.service import DEFAULT_TTL, mint_enrollment_grant
from app.modules.users.models import User

router = APIRouter(prefix="/api/enrollment", tags=["enrollment"])

# Upper bound of an admin-chosen validity: a token handed over by mail or chat
# needs longer than DEFAULT_TTL, but the single-use secret should not outlive a day.
MAX_TTL_MINUTES = 24 * 60


def _mint_token(
    db: Session, subject_id: str, browser: bool, ttl: datetime.timedelta = DEFAULT_TTL
) -> dict:
    """Persist a one-time access-scoped enrollment token for ``subject_id`` and
    return the redeemable grant. Identity (the cert CN) is issuer-dictated to
    ``subject_id``, never taken from the client's CSR; hashed at rest with the
    same SHA-256 the ca-issuer consumes by. ``browser=true`` flags a long-lived
    leaf (D5): the browser cannot auto-renew, so it gets a long cert + manual
    re-import; the desktop exports it as a PKCS12 for the browser cert store (A5c)."""
    raw_token, expires_at = mint_enrollment_grant(
        db, subject_id, SCOPE_ACCESS, browser=browser, ttl=ttl
    )
    return {
        "token": raw_token,
        "subjectId": subject_id,
        "scope": SCOPE_ACCESS,
        "browser": browser,
        # The client derives the enroll host from its own (already-trusted) server
        # URL + this port (the gateway's certless enroll plane).
        "enrollPort": ENROLL_PORT,
        "expiresAt": iso_utc(expires_at),
    }


def _browser_detail(browser: bool) -> str:
    # A browser leaf is long-lived (LEAF_DAYS_BROWSER, ~1 year) and never renews, so
    # the issuer never re-checks is_active — it is only revocable via data-plane
    # enforcement (MTLS_ENFORCE=true). Flag that in the audit trail so every long-lived
    # grant, self-minted or for another user, is greppable (3.32, R-0204).
    if browser:
        return "browser=True (long-lived leaf, revocable only under MTLS_ENFORCE=true)"
    return "browser=False"


@router.post("/token", response_model=EnrollmentGrantOut)
def mint_self_enrollment_token(
    request: Request,
    browser: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mint a one-time access-scoped enrollment token for the logged-in user.

    The self-service door: the caller authenticates with its JWT and mints a
    token for *its own* identity, then redeems it at the ca-issuer."""
    res = _mint_token(db, current_user.username, browser)
    audit.record(
        db,
        "enrollment.token.minted",
        object_type="user",
        object_id=current_user.username,
        detail=f"{_browser_detail(browser)} (self)",
        actor=actor_from_request(request),
    )
    return res


class EnrollmentTokenForRequest(RequestModel):
    username: str
    browser: bool = False
    ttl_minutes: int = Field(DEFAULT_TTL // datetime.timedelta(minutes=1), ge=1, le=MAX_TTL_MINUTES)


@router.post("/token/for", response_model=EnrollmentGrantOut)
def mint_enrollment_token_for(
    data: EnrollmentTokenForRequest,
    request: Request,
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
    res = _mint_token(
        db, target.username, data.browser, datetime.timedelta(minutes=data.ttl_minutes)
    )
    audit.record(
        db,
        "enrollment.token.minted_for",
        object_type="user",
        object_id=target.username,
        # The validity is admin-chosen here, so a longer-lived grant stays greppable.
        detail=f"{_browser_detail(data.browser)}, ttl={data.ttl_minutes}min",
        actor=actor_from_request(request),
    )
    return res


@router.post("/self/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_own_device(
    request: Request,
    db: Session = Depends(get_db),
    identity: ClientIdentity = Depends(require_scope(SCOPE_ACCESS)),
):
    """Revoke the device that calls: the line of the client certificate this request
    presents (R-0224). Holding that certificate and its key is the proof, so no JWT
    is needed — a device resets its identity at the login screen too. A certificate
    already revoked never gets here: the scope guard refuses it with ERR_CERT_REVOKED."""
    # A device of a user: an agent is retired by re-provisioning, not here.
    own = identity.verified and identity.scope == SCOPE_ACCESS and identity.fingerprint
    line = line_of(db, identity.fingerprint) if own else None
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No verified client certificate: there is no device to revoke",
        )
    if not revoke_line(db, line.id, "self"):
        return
    db.commit()
    audit.record(
        db,
        "device.revoked",
        actor=Actor("user", None, identity.cn, resolve_client_ip(request)),
        object_type="device",
        object_id=line.id,
        object_label=identity.cn,
        detail="reason=self",
    )
