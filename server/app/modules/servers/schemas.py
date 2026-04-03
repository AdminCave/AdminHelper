from pydantic import BaseModel
from typing import Optional


class ServerCreate(BaseModel):
    name: str
    hostname: str
    os_type: Optional[str] = None
    tags: Optional[list[str]] = []
    notes: Optional[str] = ""
    customer_group_id: Optional[str] = None


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    hostname: Optional[str] = None
    os_type: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    customer_group_id: Optional[str] = None
