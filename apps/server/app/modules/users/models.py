# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


user_server_assoc = Table(
    "user_servers",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("server_id", String, ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True),
)


class TokenBlacklist(Base):
    """Revoked JWT tokens (e.g. after logout or password change)."""
    __tablename__ = "token_blacklist"

    jti = Column(String, primary_key=True)  # JWT ID
    expires_at = Column(DateTime, nullable=False)  # automatic cleanup after expiry


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    servers = relationship("Server", secondary=user_server_assoc, lazy="selectin")
