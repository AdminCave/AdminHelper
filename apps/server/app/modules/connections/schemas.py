# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    # The desktop/web clients only render ssh/rdp/web; reject anything else at
    # the boundary instead of persisting a kind no consumer can handle.
    kind: Literal["ssh", "rdp", "web"]
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
    # Same gate as ConnectionCreate: no client renders anything but ssh/rdp/web,
    # so reject others here too — otherwise PUT could persist a kind that Create
    # rejects and no consumer (launcher, hub) can handle.
    kind: Optional[Literal["ssh", "rdp", "web"]] = None
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
