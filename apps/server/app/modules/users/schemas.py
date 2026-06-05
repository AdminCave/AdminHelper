# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pydantic import BaseModel, Field
from typing import Optional


# Usernames are interpolated into FRP TOML and used as PKI/cert file stems,
# so restrict them to a safe charset (see frp/config_generator + pki.py).
_USERNAME_PATTERN = r"^[a-zA-Z0-9._-]+$"


# Auth
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class BootstrapRequest(BaseModel):
    """Creates the first admin user using the bootstrap token from the server logs."""
    token: str
    username: str = Field(min_length=3, max_length=64, pattern=_USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=128)


class UserMe(BaseModel):
    id: int
    username: str
    is_admin: bool

    model_config = {"from_attributes": True}


# Users
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=_USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False
    server_ids: list[str] = []


class UserUpdate(BaseModel):
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    is_admin: Optional[bool] = None
    server_ids: Optional[list[str]] = None
