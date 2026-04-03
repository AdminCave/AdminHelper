from pydantic import BaseModel
from typing import Any, Literal, Optional


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


class ImportRequest(BaseModel):
    connections: list[dict[str, Any]]
    mode: Literal["merge", "replace"]
