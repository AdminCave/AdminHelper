# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.auth import (
    blacklist_token,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_user_from_refresh_token,
    hash_api_key,
    hash_password,
    is_token_blacklisted,
    username_from_token_unverified,
    verify_password,
)
from app.core.config import BOOTSTRAP_SETUP_FILE, BOOTSTRAP_TOKEN_FILE, REFRESH_TOKEN_EXPIRE_DAYS
from app.core.database import get_db
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


def _resolve_refresh_token(request: Request, body_token: str | None) -> str | None:
    """Refresh token from the request body (non-browser clients) or, failing
    that, the HttpOnly cookie (browser)."""
    return body_token or request.cookies.get(REFRESH_COOKIE_NAME)


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = resolve_client_ip(request)
    _check_rate_limit(ip)

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
    access = create_access_token({"sub": user.username})
    refresh = create_refresh_token({"sub": user.username})
    _set_refresh_cookie(request, response, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


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
        logger.warning(
            "Refresh-Token-Reuse erkannt von IP=%s — moeglicher Token-Diebstahl",
            resolve_client_ip(request),
        )
        # Containment: a replayed (already-rotated) refresh token is a theft
        # signal. Kill the WHOLE token family for this user via the validity
        # watermark — otherwise the attacker's already-rotated chain (which they
        # obtained by refreshing first) stays valid indefinitely; only the single
        # replayed token would be blocked.
        reused_username = username_from_token_unverified(token)
        if reused_username:
            reused_user = db.query(User).filter(User.username == reused_username).first()
            if reused_user is not None:
                reused_user.tokens_valid_after = utcnow_naive()
                db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder abgelaufener Refresh-Token",
        )

    user = get_user_from_refresh_token(token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder abgelaufener Refresh-Token",
        )

    # Rotation: blacklist the old refresh token immediately so it cannot be used
    # again. A parallel attacker with a copy of the token thereby fails from the
    # legitimate client's next refresh onward.
    blacklist_token(token, db)

    access = create_access_token({"sub": user.username})
    refresh = create_refresh_token({"sub": user.username})
    _set_refresh_cookie(request, response, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    data: LogoutRequest | None = None,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Add the access and (optionally) refresh token to the blacklist and clear
    the refresh cookie."""
    uname = None
    if credentials:
        blacklist_token(credentials.credentials, db)
        uname = username_from_token_unverified(credentials.credentials)
    refresh = _resolve_refresh_token(request, data.refresh_token if data else None)
    if refresh:
        blacklist_token(refresh, db)
    _clear_refresh_cookie(response)
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
    return current_user


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
        except OSError:
            logger.warning("Bootstrap-Datei konnte nicht geloescht werden: %s", f)

    _reset_rate_limit(ip)
    logger.info("Bootstrap erfolgreich: Admin '%s' angelegt von IP=%s", user.username, ip)

    access = create_access_token({"sub": user.username})
    refresh = create_refresh_token({"sub": user.username})
    _set_refresh_cookie(request, response, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)
