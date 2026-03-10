from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# Auth
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


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


class UserUpdate(BaseModel):
    password: Optional[str] = None
    is_admin: Optional[bool] = None


class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# API Keys
class ApiKeyCreate(BaseModel):
    name: str
    permission: str  # "read" or "read_write"


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    permission: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str  # Nur beim Erstellen zurückgegeben


# Webhooks
class WebhookCreate(BaseModel):
    name: str
    description: Optional[str] = None
    script: str


class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    script: Optional[str] = None


class WebhookResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WebhookDetailResponse(WebhookResponse):
    script: str


class WebhookCreatedResponse(WebhookDetailResponse):
    token: str  # Nur beim Erstellen / Token-Rotation zurückgegeben


# Connections (passthrough, gleiche Struktur wie Client)
class Connection(BaseModel):
    id: str
    name: str
    kind: str
    host: Optional[str] = ""
    port: Optional[int] = None
    username: Optional[str] = ""
    domain: Optional[str] = ""
    keyPath: Optional[str] = ""
    url: Optional[str] = ""
    notes: Optional[str] = ""
    tags: Optional[list[str]] = []
    trustCert: Optional[bool] = False
    lastUsed: Optional[str] = None
    scalingMode: Optional[str] = None

    model_config = {"extra": "allow"}
