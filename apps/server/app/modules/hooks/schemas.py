# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.core.bounds import SafeText
from app.modules.hooks.scheduler import INTERVAL_MAP

VALID_EVENTS = [
    "connection.created",
    "connection.updated",
    "connection.deleted",
    "connections.imported",
    "user.created",
    "user.deleted",
    "server.created",
    "server.updated",
    "server.deleted",
    "server.startup",
    "frp.config.created",
    "frp.config.updated",
    "frp.config.deleted",
    "frp.tunnel.created",
    "frp.tunnel.updated",
    "frp.tunnel.deleted",
    "playbook.created",
    "playbook.updated",
    "playbook.deleted",
    "alert.triggered",
]

VALID_INTERVALS = list(INTERVAL_MAP)


# Every field below is stored verbatim in a Postgres text column, so a NUL byte
# in any of them died in the driver (HTTP 500). Measured on `script` in the fuzz
# run of 2026-09-22 after the exclusions came off; the siblings share the column
# type and the path in, so they share the type.
class HookCreate(BaseModel):
    name: SafeText
    description: Optional[SafeText] = None
    hook_type: Literal["webhook", "event", "schedule"]
    script: SafeText
    event_triggers: Optional[list[SafeText]] = None
    schedule_interval: Optional[SafeText] = None


class HookUpdate(BaseModel):
    name: Optional[SafeText] = None
    description: Optional[SafeText] = None
    script: Optional[SafeText] = None
    enabled: Optional[bool] = None
    event_triggers: Optional[list[SafeText]] = None
    schedule_interval: Optional[SafeText] = None


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
