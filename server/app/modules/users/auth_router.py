import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import verify_password, create_access_token, create_refresh_token, get_current_user, get_user_from_refresh_token
from app.core.middleware import resolve_client_ip
from app.modules.users.schemas import LoginRequest, RefreshRequest, TokenResponse, UserMe
from app.modules.users.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Rate-Limiting: max 5 fehlgeschlagene Login-Versuche pro IP innerhalb von 60 Sekunden
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 60
_login_attempts: dict[str, list[float]] = defaultdict(list)
_CLEANUP_INTERVAL = 300  # Alle 5 Minuten verwaiste Einträge bereinigen
_last_cleanup = 0.0


def _check_rate_limit(ip: str) -> None:
    global _last_cleanup
    now = time.monotonic()

    # Periodisch alle abgelaufenen Einträge bereinigen (Memory-Leak verhindern)
    if now - _last_cleanup > _CLEANUP_INTERVAL:
        _last_cleanup = now
        stale = [k for k, v in _login_attempts.items()
                 if all(now - t >= _WINDOW_SECONDS for t in v)]
        for k in stale:
            del _login_attempts[k]

    attempts = _login_attempts[ip]
    # Alte Einträge für diese IP entfernen
    _login_attempts[ip] = [t for t in attempts if now - t < _WINDOW_SECONDS]
    if len(_login_attempts[ip]) >= _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Zu viele Login-Versuche. Bitte {_WINDOW_SECONDS} Sekunden warten.",
        )


def _record_failed_attempt(ip: str) -> None:
    _login_attempts[ip].append(time.monotonic())


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

    # Bei erfolgreichem Login: Zähler zurücksetzen
    _login_attempts.pop(ip, None)
    access = create_access_token({"sub": user.username})
    refresh = create_refresh_token({"sub": user.username})
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(data: RefreshRequest, db: Session = Depends(get_db)):
    user = get_user_from_refresh_token(data.refresh_token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder abgelaufener Refresh-Token",
        )
    access = create_access_token({"sub": user.username})
    refresh = create_refresh_token({"sub": user.username})
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.get("/me", response_model=UserMe)
def me(current_user: User = Depends(get_current_user)):
    return current_user
