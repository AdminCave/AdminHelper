# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from typing import Any

from sqlalchemy import Column, DateTime, String

from app.core.database import Base
from app.core.time import utc_now_sql


class Playbook(Base):
    __tablename__ = "ansible_playbooks"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    description = Column(String, nullable=True)
    tags = Column(String, nullable=True)  # JSON-Array als String
    created_at = Column(DateTime, server_default=utc_now_sql())
    updated_at = Column(DateTime, onupdate=utc_now_sql())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "filename": self.filename,
            "description": self.description or "",
            "tags": json.loads(self.tags) if self.tags else [],
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
