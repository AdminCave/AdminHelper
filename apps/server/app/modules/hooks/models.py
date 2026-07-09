# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from sqlalchemy import Boolean, Column, DateTime, String

from app.core.database import Base
from app.core.time import utc_now_sql


class Hook(Base):
    __tablename__ = "hooks"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    hook_type = Column(String, nullable=False)  # "webhook", "event", "schedule"
    script = Column(String, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=utc_now_sql())

    # Webhook-specific
    hashed_token = Column(String, unique=True, nullable=True, index=True)

    # Event-specific: JSON array as a string, e.g. '["connection.created"]'
    event_triggers = Column(String, nullable=True)

    # Schedule-specific
    schedule_interval = Column(String, nullable=True)  # "5m", "1h", … or cron
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
