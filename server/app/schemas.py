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


# Hooks
VALID_EVENTS = [
    "connection.created",
    "connection.updated",
    "connection.deleted",
    "connections.imported",
    "user.created",
    "user.deleted",
    "server.startup",
]

VALID_INTERVALS = ["5m", "15m", "30m", "1h", "6h", "12h", "24h"]


class HookCreate(BaseModel):
    name: str
    description: Optional[str] = None
    hook_type: str  # "webhook", "event", "schedule"
    script: str
    event_triggers: Optional[list[str]] = None
    schedule_interval: Optional[str] = None


class HookUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    script: Optional[str] = None
    enabled: Optional[bool] = None
    event_triggers: Optional[list[str]] = None
    schedule_interval: Optional[str] = None


class HookResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    hook_type: str
    enabled: bool
    created_at: Optional[datetime] = None
    event_triggers: Optional[list[str]] = None
    schedule_interval: Optional[str] = None
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None


class HookDetailResponse(HookResponse):
    script: str


class HookCreatedResponse(HookDetailResponse):
    token: Optional[str] = None  # Nur bei Webhook-Typ beim Erstellen / Token-Rotation


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
