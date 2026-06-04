# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import (
    verify_password,
    hash_password,
    hash_api_key,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_user_from_refresh_token,
    blacklist_token,
    is_token_blacklisted,
)
from app.core.config import BOOTSTRAP_TOKEN_FILE
from app.core.middleware import resolve_client_ip
from app.core.rate_limit import get_backend as get_rate_limit_backend
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.modules.users.schemas import (
    BootstrapRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserMe,
)
from app.modules.users.models import User

logger = logging.getLogger("adminhelper.auth_router")

bearer_scheme = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Rate limiting: max 5 failed login attempts per IP within 60 seconds
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 60


def _rate_limit_key(ip: str) -> str:
    return f"auth:fail:{ip}"


def _check_rate_limit(ip: str) -> None:
    backend = get_rate_limit_backend()
    if backend.get_count(_rate_limit_key(ip)) >= _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Zu viele Login-Versuche. Bitte {_WINDOW_SECONDS} Sekunden warten.",
        )


def _record_failed_attempt(ip: str) -> None:
    get_rate_limit_backend().increment(_rate_limit_key(ip), _WINDOW_SECONDS)


def _reset_rate_limit(ip: str) -> None:
    get_rate_limit_backend().reset(_rate_limit_key(ip))


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = resolve_client_ip(request)
    _check_rate_limit(ip)

    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.hashed_password):
        _record_failed_attempt(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Zugangsdaten",
        )

    # On successful login: reset the counter
    _reset_rate_limit(ip)
    access = create_access_token({"sub": user.username})
    refresh = create_refresh_token({"sub": user.username})
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(data: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    # Reuse detection: an already-revoked refresh token that is submitted
    # again is a theft signal. It differs from "expired/invalid" by the
    # explicitly set blacklist entry.
    if is_token_blacklisted(data.refresh_token, db):
        logger.warning(
            "Refresh-Token-Reuse erkannt von IP=%s — moeglicher Token-Diebstahl",
            resolve_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder abgelaufener Refresh-Token",
        )

    user = get_user_from_refresh_token(data.refresh_token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder abgelaufener Refresh-Token",
        )

    # Rotation: blacklist the old refresh token immediately so it cannot be used
    # again. A parallel attacker with a copy of the token thereby fails from the
    # legitimate client's next refresh onward.
    blacklist_token(data.refresh_token, db)

    access = create_access_token({"sub": user.username})
    refresh = create_refresh_token({"sub": user.username})
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/logout")
def logout(
    data: LogoutRequest | None = None,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Add the access and (optionally) refresh token to the blacklist."""
    if credentials:
        blacklist_token(credentials.credentials, db)
    if data and data.refresh_token:
        blacklist_token(data.refresh_token, db)
    return {"detail": "Abgemeldet"}


@router.get("/me", response_model=UserMe)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/bootstrap", response_model=TokenResponse, status_code=201)
def bootstrap(data: BootstrapRequest, request: Request, db: Session = Depends(get_db)):
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
        _record_failed_attempt(ip)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Server ist bereits initialisiert",
        )

    if not BOOTSTRAP_TOKEN_FILE.exists():
        _record_failed_attempt(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kein Bootstrap-Token aktiv",
        )

    expected = BOOTSTRAP_TOKEN_FILE.read_text().strip()
    if hash_api_key(data.token) != expected:
        _record_failed_attempt(ip)
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
    db.commit()
    db.refresh(user)

    # Consume the token — even if deleting the file fails, the 'count() > 0'
    # check above remains the effective protection.
    try:
        BOOTSTRAP_TOKEN_FILE.unlink()
    except OSError:
        logger.warning("Bootstrap-Token-Datei konnte nicht geloescht werden: %s", BOOTSTRAP_TOKEN_FILE)

    _reset_rate_limit(ip)
    logger.info("Bootstrap erfolgreich: Admin '%s' angelegt von IP=%s", user.username, ip)

    access = create_access_token({"sub": user.username})
    refresh = create_refresh_token({"sub": user.username})
    return TokenResponse(access_token=access, refresh_token=refresh)
