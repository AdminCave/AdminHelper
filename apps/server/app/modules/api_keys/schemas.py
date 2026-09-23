# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.core.bounds import SafeText


class ApiKeyCreate(BaseModel):
    # name lands verbatim in Column(String); a NUL byte died in the driver
    # (HTTP 500), found by the fuzzer on 2026-09-23.
    name: SafeText
    permission: Literal["read", "read_write"]


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    permission: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str  # Returned only on creation
