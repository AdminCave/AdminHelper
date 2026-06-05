# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pydantic import BaseModel, Field, field_validator
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


class ConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    kind: str = Field(..., min_length=1, max_length=50)
    host: Optional[str] = ""
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = ""
    domain: Optional[str] = ""
    keyPath: Optional[str] = ""
    url: Optional[str] = ""
    notes: Optional[str] = ""
    tags: Optional[list[str]] = []
    trustCert: Optional[bool] = False
    lastUsed: Optional[str] = None
    scalingMode: Optional[str] = None
    serverId: Optional[str] = None

    model_config = {"extra": "allow"}

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name darf nicht leer sein")
        return v.strip()


class ConnectionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    kind: Optional[str] = Field(None, min_length=1, max_length=50)
    host: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = None
    domain: Optional[str] = None
    keyPath: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    trustCert: Optional[bool] = None
    lastUsed: Optional[str] = None
    scalingMode: Optional[str] = None
    serverId: Optional[str] = None

    model_config = {"extra": "allow"}

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Name darf nicht leer sein")
        return v.strip() if v else v


class ImportRequest(BaseModel):
    connections: list[dict[str, Any]]
    mode: Literal["merge", "replace"]
