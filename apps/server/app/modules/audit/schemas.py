# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Optional

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    """One audit entry, as AuditLog.to_dict writes it."""

    id: int
    timestamp: Optional[str]
    actorType: str
    actorId: Optional[str]
    actorLabel: Optional[str]
    action: str
    objectType: Optional[str]
    objectId: Optional[str]
    objectLabel: Optional[str]
    sourceIp: Optional[str]
    status: str
    detail: Optional[str]
