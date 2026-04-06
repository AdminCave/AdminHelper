import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS
from app.core.database import get_db
from app.modules.users.models import User
from app.modules.api_keys.models import ApiKey

bearer_scheme = HTTPBearer(auto_error=False)


def _prehash(password: str) -> bytes:
    """SHA-256-Prehash, damit Passwörter > 72 Bytes funktionieren (bcrypt-Limit)."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)  # 44 Bytes, sicher unter dem 72-Byte-Limit


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prehash(plain), hashed.encode("utf-8"))


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _get_user_from_token(token: str, db: Session, expected_type: str = "access") -> Optional[User]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type", "access") != expected_type:
            return None
        username: str = payload.get("sub")
        if not username:
            return None
    except InvalidTokenError:
        return None
    return db.query(User).filter(User.username == username).first()


def get_user_from_refresh_token(token: str, db: Session) -> Optional[User]:
    return _get_user_from_token(token, db, expected_type="refresh")


def _get_api_key_from_header(request: Request, db: Session) -> Optional[ApiKey]:
    key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if not key:
        return None
    hashed = hash_api_key(key)
    return db.query(ApiKey).filter(ApiKey.hashed_key == hashed).first()


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    user = None

    if credentials:
        user = _get_user_from_token(credentials.credentials, db)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nicht authentifiziert",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin-Rechte erforderlich")
    return current_user


class ApiKeyOrUser:
    """Dependency: akzeptiert JWT-Bearer ODER API-Key. Gibt (user_or_none, apikey_or_none) zurück."""

    def __init__(self, require_write: bool = False):
        self.require_write = require_write

    def __call__(
        self,
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
        db: Session = Depends(get_db),
    ):
        # API-Key prüfen
        api_key = _get_api_key_from_header(request, db)
        if api_key:
            if self.require_write and api_key.permission != "read_write":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Schreibzugriff erforderlich")
            return None, api_key

        # JWT prüfen
        if credentials:
            user = _get_user_from_token(credentials.credentials, db)
            if user:
                return user, None

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nicht authentifiziert",
            headers={"WWW-Authenticate": "Bearer"},
        )
