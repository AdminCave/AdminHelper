# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import base64
import hashlib
import logging
import secrets
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

logger = logging.getLogger("adminhelper.auth")

from app.core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS
from app.core.database import get_db
from app.modules.users.models import User, TokenBlacklist
from app.modules.api_keys.models import ApiKey

bearer_scheme = HTTPBearer(auto_error=False)


def _prehash(password: str) -> bytes:
    """SHA-256 prehash so passwords > 72 bytes work (bcrypt limit)."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)  # 44 bytes, safely under the 72-byte limit


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
    to_encode.update({"exp": expire, "type": "access", "jti": str(_uuid.uuid4())})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh", "jti": str(_uuid.uuid4())})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _get_user_from_token(token: str, db: Session, expected_type: str = "access") -> Optional[User]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type", "access") != expected_type:
            return None
        username: str = payload.get("sub")
        if not username:
            return None
        # Blacklist check: reject revoked tokens
        jti = payload.get("jti")
        if jti and db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first():
            return None
    except InvalidTokenError:
        return None
    return db.query(User).filter(User.username == username).first()


def blacklist_token(token: str, db: Session) -> bool:
    """Add a token to the blacklist (e.g. on logout or refresh rotation).
    Returns True if newly added, False if already present or the token is
    invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except InvalidTokenError:
        return False
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti or not exp:
        return False
    if db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first():
        return False
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
    db.add(TokenBlacklist(jti=jti, expires_at=expires_at))
    db.commit()
    return True


def is_token_blacklisted(token: str, db: Session) -> bool:
    """Checks whether the token (by its jti) has already been revoked.
    Required for refresh-reuse detection: a blacklisted refresh token that is
    submitted again is a theft signal."""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )
    except InvalidTokenError:
        return False
    jti = payload.get("jti")
    if not jti:
        return False
    return db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first() is not None


def cleanup_expired_blacklist(db: Session) -> int:
    """Remove expired entries from the blacklist."""
    now = datetime.now(timezone.utc)
    count = db.query(TokenBlacklist).filter(TokenBlacklist.expires_at < now).delete()
    db.commit()
    return count


def get_user_from_refresh_token(token: str, db: Session) -> Optional[User]:
    return _get_user_from_token(token, db, expected_type="refresh")


def _get_api_key(request: Request, db: Session) -> Optional[ApiKey]:
    # Header preferred; query-param fallback for the browser extension and
    # sync URLs (curl/wget). Note: the query param may end up in server logs,
    # so the docs recommend the header path.
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
    """Dependency: accepts a JWT bearer OR an API key. Returns (user_or_none, apikey_or_none)."""

    def __init__(self, require_write: bool = False, require_admin: bool = False):
        self.require_write = require_write
        self.require_admin = require_admin

    def __call__(
        self,
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
        db: Session = Depends(get_db),
    ):
        # Check API key
        api_key = _get_api_key(request, db)
        if api_key:
            if self.require_write and api_key.permission != "read_write":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Schreibzugriff erforderlich")
            return None, api_key

        # Check JWT
        if credentials:
            user = _get_user_from_token(credentials.credentials, db)
            if user:
                if self.require_admin and not user.is_admin:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin-Rechte erforderlich")
                return user, None

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nicht authentifiziert",
            headers={"WWW-Authenticate": "Bearer"},
        )
