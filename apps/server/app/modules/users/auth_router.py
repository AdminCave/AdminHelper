# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import secrets
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import config
from app.core.auth import (
    blacklist_token,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_user_from_refresh_token,
    hash_api_key,
    hash_password,
    is_token_blacklisted,
    token_claims,
    user_id_from_token_unverified,
    username_from_token_unverified,
    verify_password,
)
from app.core.config import BOOTSTRAP_SETUP_FILE, BOOTSTRAP_TOKEN_FILE, REFRESH_TOKEN_EXPIRE_DAYS
from app.core.database import get_db
from app.core.identity import require_cert_user
from app.core.middleware import resolve_client_ip
from app.core.rate_limit import get_backend as get_rate_limit_backend
from app.core.request_context import Actor
from app.core.time import utcnow_naive
from app.modules.audit import service as audit
from app.modules.notifications.service import default_admin_subscription
from app.modules.users.models import User
from app.modules.users.schemas import (
    BootstrapRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserMe,
)

logger = logging.getLogger("adminhelper.auth_router")

bearer_scheme = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Rate limiting: max 5 failed login attempts per IP within 60 seconds
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 60

# A fixed valid bcrypt hash: on a login for a non-existent user we still run one
# verify_password against it, so a missing username costs the same ~bcrypt time as a
# wrong password — otherwise the short-circuit is a timing oracle for enumeration (3.94).
_DUMMY_HASH = hash_password("login-timing-equalizer")
# One key of its own; the two-key space of the identity locks (enrollment/models.py) does not
# overlap with it.
_BOOTSTRAP_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('adminhelper.bootstrap'))"


def _rate_limit_key(ip: str) -> str:
    return f"auth:fail:{ip}"


def _check_rate_limit(ip: str) -> None:
    # Increment atomically and check the result. Reading the count here and incrementing only after
    # a failed verify let N parallel requests all see count=0, all pass, and all run bcrypt —
    # bypassing the limit and forcing bulk bcrypt work. INCR is the backend's race-free op, so every
    # attempt counts up front; a successful login resets the counter via _reset_rate_limit (4.141).
    count = get_rate_limit_backend().increment(_rate_limit_key(ip), _WINDOW_SECONDS)
    if count > _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Zu viele Login-Versuche. Bitte {_WINDOW_SECONDS} Sekunden warten.",
        )


def _reset_rate_limit(ip: str) -> None:
    get_rate_limit_backend().reset(_rate_limit_key(ip))


# ── Refresh-token cookie ──────────────────────────────────────────────
# Browser clients keep the long-lived refresh token in an HttpOnly cookie so
# JavaScript (and thus an XSS) cannot read it; it is scoped to /api/auth and
# SameSite=Strict so it is never sent cross-site (the only CSRF protection
# needed, since /refresh + /logout are the only cookie-reading endpoints and
# the access token stays a Bearer header). Non-browser clients (desktop, CLI)
# ignore the cookie and keep using the request body — both paths are accepted.
# A browser request (Sec-Fetch-Site present) gets the refresh token only as the
# cookie: its JSON field is "" (_token_response).
REFRESH_COOKIE_NAME = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/auth"
_REFRESH_COOKIE_MAX_AGE = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


def _set_refresh_cookie(request: Request, response: Response, token: str) -> None:
    # Secure follows the request scheme: True on real https (and proxies that
    # forward the proto), False on http://localhost dev / the test client, where
    # the browser would otherwise drop the cookie. HttpOnly + SameSite hold either way.
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=_REFRESH_COOKIE_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path=_REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=_REFRESH_COOKIE_PATH)


def _token_response(
    request: Request, response: Response, access: str, refresh: str
) -> TokenResponse:
    _set_refresh_cookie(request, response, refresh)
    # Only a browser sends Sec-Fetch-Site (Fetch Metadata; a forbidden header, page
    # scripts can neither set nor drop it). Node fetch sends Sec-Fetch-Mode but not
    # Sec-Fetch-Site; desktop (reqwest), CLI and scripts send neither. The field stays
    # a required string, "" for a browser: omitting it or making it nullable would
    # break the response schema.
    body_refresh = "" if "sec-fetch-site" in request.headers else refresh
    return TokenResponse(access_token=access, refresh_token=body_refresh)


def _resolve_refresh_token(request: Request, body_token: str | None) -> str | None:
    """Refresh token from the request body (non-browser clients) or, failing
    that, the HttpOnly cookie (browser)."""
    return body_token or request.cookies.get(REFRESH_COOKIE_NAME)


def _refuse_reused_refresh(token: str, request: Request, db: Session) -> NoReturn:
    logger.warning(
        "Refresh-Token-Reuse erkannt von IP=%s — moeglicher Token-Diebstahl",
        resolve_client_ip(request),
    )
    # Containment: a replayed (already-rotated) refresh token is a theft
    # signal. Kill the WHOLE token family for this user via the validity
    # watermark — otherwise the attacker's already-rotated chain (which they
    # obtained by refreshing first) stays valid indefinitely; only the single
    # replayed token would be blocked.
    # By the account id: a name may belong to a newer account than the token's.
    reused_id = user_id_from_token_unverified(token)
    if reused_id is not None:
        reused_user = db.get(User, reused_id)
        if reused_user is not None:
            reused_user.tokens_valid_after = utcnow_naive()
            db.commit()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Ungültiger oder abgelaufener Refresh-Token",
    )


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = resolve_client_ip(request)
    _check_rate_limit(ip)

    # The certificate has to belong to the user who signs in (R-0223). Checked before
    # the password, so the answer says nothing about it.
    try:
        require_cert_user(request, data.username, db)
    except HTTPException:
        audit.record(
            db,
            "auth.login_failed",
            status="failure",
            actor=Actor("anonymous", None, data.username, ip),
            object_type="user",
            object_label=data.username,
        )
        raise

    user = db.query(User).filter(User.username == data.username).first()
    # Always run one bcrypt verify — against a dummy hash when the user is missing — so
    # the response time doesn't reveal whether the username exists (3.94).
    if user:
        password_ok = verify_password(data.password, user.hashed_password)
    else:
        verify_password(data.password, _DUMMY_HASH)
        password_ok = False
    if not password_ok:
        audit.record(
            db,
            "auth.login_failed",
            status="failure",
            actor=Actor("anonymous", None, data.username, ip),
            object_type="user",
            object_label=data.username,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Zugangsdaten",
        )

    # On successful login: reset the counter
    _reset_rate_limit(ip)
    audit.record(
        db,
        "auth.login",
        actor=Actor("user", str(user.id), user.username, ip),
        object_type="user",
        object_id=user.id,
        object_label=user.username,
    )
    access = create_access_token(token_claims(user))
    refresh = create_refresh_token(token_claims(user))
    return _token_response(request, response, access, refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    request: Request,
    response: Response,
    data: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    token = _resolve_refresh_token(request, data.refresh_token if data else None)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder abgelaufener Refresh-Token",
        )

    # Reuse detection: an already-revoked refresh token that is submitted
    # again is a theft signal. It differs from "expired/invalid" by the
    # explicitly set blacklist entry.
    if is_token_blacklisted(token, db):
        _refuse_reused_refresh(token, request, db)

    user = get_user_from_refresh_token(token, db)
    if not user:
        # A concurrent call with the same token may have committed its blacklist row
        # since the check above; then this lookup failed on that row, which is reuse.
        if is_token_blacklisted(token, db):
            _refuse_reused_refresh(token, request, db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder abgelaufener Refresh-Token",
        )
    # Before the rotation, so a refused refresh does not use up the token.
    require_cert_user(request, user.username, db)

    # Issued before the blacklist commit: their `iat` then precedes the watermark a
    # concurrent call with the same token sets once it fails after that commit, so a
    # reuse kills this pair too. Issued after it, a delayed call could stamp a later
    # second and outlive the watermark (`iat` has whole seconds, core/auth.py).
    access = create_access_token(token_claims(user))
    refresh = create_refresh_token(token_claims(user))

    # Rotation: only the call that blacklists the old refresh token gets the new
    # pair. False means the jti was already there (a concurrent call with the same
    # token won) or the token carries no jti/exp; either way it is reuse, and the
    # pair above is discarded.
    if not blacklist_token(token, db):
        _refuse_reused_refresh(token, request, db)

    return _token_response(request, response, access, refresh)


# The route works without a bearer (the refresh token from body or cookie is blacklisted
# and the cookie cleared), so the schema declares the auth optional. FastAPI deep-merges
# openapi_extra and appends lists, which turns the derived [{HTTPBearer}] into
# [{HTTPBearer}, {}] — `{}` being OpenAPI's "no auth" alternative (R-0054).
@router.post("/logout", openapi_extra={"security": [{}]})
def logout(
    request: Request,
    response: Response,
    data: LogoutRequest | None = None,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Blacklist the bearer token, if one is sent, and the refresh token from body
    or cookie; clear the refresh cookie."""
    # Audited only when this call revoked a token: a logout without a token, with an
    # invalid or expired one, or a repeat of an earlier logout ends no session.
    # Both tokens are blacklisted unconditionally — no short circuit between them.
    uname = None
    revoked = False
    if credentials:
        revoked = blacklist_token(credentials.credentials, db)
        uname = username_from_token_unverified(credentials.credentials)
    refresh = _resolve_refresh_token(request, data.refresh_token if data else None)
    if refresh:
        refresh_revoked = blacklist_token(refresh, db)
        revoked = revoked or refresh_revoked
        if refresh_revoked and not uname:
            uname = username_from_token_unverified(refresh)
    _clear_refresh_cookie(response)
    if revoked:
        audit.record(
            db,
            "auth.logout",
            actor=Actor("user", None, uname, resolve_client_ip(request)),
            object_type="user",
            object_label=uname,
        )
    return {"detail": "Abgemeldet"}


@router.get("/me", response_model=UserMe)
def me(current_user: User = Depends(get_current_user)):
    return UserMe(
        id=current_user.id,
        username=current_user.username,
        is_admin=current_user.is_admin,
        idle_timeout_minutes=config.WEB_IDLE_TIMEOUT_MINUTES,
    )


@router.post("/bootstrap", response_model=TokenResponse, status_code=201)
def bootstrap(
    data: BootstrapRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Creates the first admin user using the setup token.

    Active only if ADMIN_PASSWORD was empty/'admin' on first start —
    the server then wrote a token to DATA_DIR/.bootstrap_token (hash) and
    showed it in the WARNING log. As soon as a user exists, the endpoint is
    permanently dead (409).
    """
    ip = resolve_client_ip(request)
    _check_rate_limit(ip)

    # Several workers serve this route: without the lock two calls with the token can both
    # see "no user" and both create an admin. Held until the commit below.
    db.execute(text(_BOOTSTRAP_LOCK_SQL))
    if db.query(User).count() > 0:
        # Server is already initialized – bootstrap is no longer possible.
        # Same response as 'no token active' to avoid disclosing the DB state.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Server ist bereits initialisiert",
        )

    if not BOOTSTRAP_TOKEN_FILE.exists():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kein Bootstrap-Token aktiv",
        )

    expected = BOOTSTRAP_TOKEN_FILE.read_text().strip()
    # Constant-time compare like the /events internal key (3.95).
    if not secrets.compare_digest(hash_api_key(data.token), expected):
        logger.warning("Bootstrap-Versuch mit ungueltigem Token von IP=%s", ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungueltiger Bootstrap-Token",
        )
    require_cert_user(request, data.username, db)

    user = User(
        username=data.username,
        hashed_password=hash_password(data.password),
        is_admin=True,
    )
    db.add(user)
    # Baseline notification rule — the bootstrap admin is the only user a
    # fresh install has (same as the other admin-create paths).
    db.flush()
    db.add(default_admin_subscription(user.id))
    db.commit()
    db.refresh(user)
    audit.record(
        db,
        "auth.bootstrap",
        actor=Actor("user", str(user.id), user.username, ip),
        object_type="user",
        object_id=user.id,
        object_label=user.username,
    )

    # Consume the token — even if deleting the file fails, the 'count() > 0'
    # check above remains the effective protection.
    for f in (BOOTSTRAP_TOKEN_FILE, BOOTSTRAP_SETUP_FILE):
        try:
            f.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("bootstrap file %s not removed (%s)", f, type(exc).__name__)

    _reset_rate_limit(ip)
    logger.info("Bootstrap erfolgreich: Admin '%s' angelegt von IP=%s", user.username, ip)

    access = create_access_token(token_claims(user))
    refresh = create_refresh_token(token_claims(user))
    return _token_response(request, response, access, refresh)
