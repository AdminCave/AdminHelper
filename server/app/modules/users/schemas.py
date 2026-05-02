from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


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
    """Erstellt den ersten Admin-User mit dem Bootstrap-Token aus den Server-Logs."""
    token: str
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class UserMe(BaseModel):
    id: int
    username: str
    is_admin: bool

    model_config = {"from_attributes": True}


# Users
class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    server_ids: list[str] = []


class UserUpdate(BaseModel):
    password: Optional[str] = None
    is_admin: Optional[bool] = None
    server_ids: Optional[list[str]] = None


class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    server_ids: list[str] = []
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
