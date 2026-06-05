# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from pydantic import BaseModel, field_validator
from typing import Optional

from app.modules.frp.schemas import _validate_tags


class PlaybookCreate(BaseModel):
    name: str
    filename: str
    description: Optional[str] = ""
    tags: list[str] = []
    content: str

    _clean_tags = field_validator("tags", mode="before")(_validate_tags)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^[\w\-. ]+\.(yml|yaml)$", v):
            raise ValueError("Dateiname muss auf .yml oder .yaml enden und darf keine Pfad-Separatoren enthalten")
        return v


class PlaybookUpdate(BaseModel):
    name: Optional[str] = None
    filename: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    content: Optional[str] = None

    _clean_tags = field_validator("tags", mode="before")(_validate_tags)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not re.match(r"^[\w\-. ]+\.(yml|yaml)$", v):
            raise ValueError("Dateiname muss auf .yml oder .yaml enden und darf keine Pfad-Separatoren enthalten")
        return v
