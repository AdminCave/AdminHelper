# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Optional

from pydantic import BaseModel, Field

from app.core.bounds import RequestModel
from app.core.time import UtcDatetime

# Usernames are interpolated into FRP TOML and used as PKI/cert file stems,
# so restrict them to a safe charset (see frp/config_generator + pki.py).
_USERNAME_PATTERN = r"^[a-zA-Z0-9._-]+$"
# Also the CLI's bound (app/cli.py): a longer password could never log in.
PASSWORD_MAX_LEN = 128


# Auth
class LoginRequest(RequestModel):
    # Bound the fields at the boundary like the rest of the module (3.96). Login stays
    # charset-tolerant (no pattern — an existing user's name is whatever it is), but an
    # unbounded username/password ties up DB + prehash work on an unauthenticated call.
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LEN)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(RequestModel):
    # Optional: browser clients send the refresh token via the HttpOnly cookie
    # instead of the body; non-browser clients (desktop, CLI) still send it here.
    refresh_token: Optional[str] = None


class LogoutRequest(RequestModel):
    refresh_token: Optional[str] = None


class BootstrapRequest(RequestModel):
    """Creates the first admin user using the bootstrap token from the server logs."""

    token: str
    username: str = Field(min_length=3, max_length=64, pattern=_USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=PASSWORD_MAX_LEN)


class UserMe(BaseModel):
    id: int
    username: str
    is_admin: bool
    idle_timeout_minutes: int


# Users
class UserCreate(RequestModel):
    username: str = Field(min_length=3, max_length=64, pattern=_USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=PASSWORD_MAX_LEN)
    is_admin: bool = False
    # No numeric bound applies — servers.id is a String column.
    server_ids: list[str] = []


class UserUpdate(RequestModel):
    password: Optional[str] = Field(default=None, min_length=8, max_length=PASSWORD_MAX_LEN)
    is_admin: Optional[bool] = None
    server_ids: Optional[list[str]] = None


class LogoutOut(BaseModel):
    detail: str


class MyServerOut(BaseModel):
    """A server assigned to the caller."""

    id: str
    name: str
    hostname: str


class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    server_ids: list[str]
    # A string, not a datetime: the builder hands out iso_utc() (UTC with Z) without
    # promising `format: date-time` in the schema (R-0064).
    created_at: Optional[str]


class DeviceResponse(BaseModel):
    """One device of a user: a line of client certificates (R-0224)."""

    id: str
    kind: str  # desktop | browser
    legacy: bool  # taken over from before the certificate register
    created_at: UtcDatetime
    revoked_at: Optional[UtcDatetime] = None
    revoked_reason: Optional[str] = None  # replaced | self | admin
    # Of the newest certificate on the line.
    fingerprint: Optional[str] = None
    not_after: Optional[UtcDatetime] = None
