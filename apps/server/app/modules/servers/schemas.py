# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pydantic import BaseModel, field_validator
from typing import Optional

from app.modules.frp.schemas import _validate_tags


class ServerCreate(BaseModel):
    name: str
    hostname: str
    os_type: Optional[str] = None
    tags: list[str] = []
    notes: Optional[str] = ""

    _clean_tags = field_validator("tags", mode="before")(_validate_tags)


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    hostname: Optional[str] = None
    os_type: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None

    _clean_tags = field_validator("tags", mode="before")(_validate_tags)
