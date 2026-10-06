# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Literal, Optional

from pydantic import BaseModel

from app.core.bounds import RequestModel
from app.core.time import UtcDatetime


class ApiKeyCreate(RequestModel):
    name: str
    permission: Literal["read", "read_write"]


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    permission: str
    created_at: Optional[UtcDatetime] = None

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str  # Returned only on creation
