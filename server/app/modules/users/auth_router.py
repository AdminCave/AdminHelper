from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import verify_password, create_access_token, create_refresh_token, get_current_user, get_user_from_refresh_token, blacklist_token
from app.core.middleware import resolve_client_ip
from app.core.rate_limit import get_backend as get_rate_limit_backend
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.modules.users.schemas import LoginRequest, RefreshRequest, TokenResponse, UserMe
from app.modules.users.models import User

bearer_scheme = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Rate-Limiting: max 5 fehlgeschlagene Login-Versuche pro IP innerhalb von 60 Sekunden
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

    # Bei erfolgreichem Login: Zähler zurücksetzen
    _reset_rate_limit(ip)
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


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Aktuellen Access-Token auf die Blacklist setzen."""
    if credentials:
        blacklist_token(credentials.credentials, db)
    return {"detail": "Abgemeldet"}


@router.get("/me", response_model=UserMe)
def me(current_user: User = Depends(get_current_user)):
    return current_user
