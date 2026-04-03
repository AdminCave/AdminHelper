from pydantic import BaseModel
from typing import Optional
from datetime import datetime


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
