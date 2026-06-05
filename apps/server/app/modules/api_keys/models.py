# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    hashed_key = Column(String, unique=True, nullable=False)
    permission = Column(String, nullable=False)  # "read" or "read_write"
    # Optional binding to exactly one server (IDOR protection for agent keys on
    # the frp/provision endpoints). NULL = global key (browser extension/sync URLs).
    server_id = Column(
        String, ForeignKey("servers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at = Column(DateTime, server_default=func.now())
