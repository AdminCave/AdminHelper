# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

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
]

VALID_INTERVALS = list(INTERVAL_MAP)


class HookCreate(BaseModel):
    name: str
    description: Optional[str] = None
    hook_type: str  # "webhook", "event", "schedule"
    script: str
    event_triggers: Optional[list[str]] = None
    schedule_interval: Optional[str] = None


class HookUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    script: Optional[str] = None
    enabled: Optional[bool] = None
    event_triggers: Optional[list[str]] = None
    schedule_interval: Optional[str] = None


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
