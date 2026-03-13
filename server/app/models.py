from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    hashed_key = Column(String, unique=True, nullable=False)
    permission = Column(String, nullable=False)  # "read" or "read_write"
    created_at = Column(DateTime, server_default=func.now())


class Hook(Base):
    __tablename__ = "hooks"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    hook_type = Column(String, nullable=False)  # "webhook", "event", "schedule"
    script = Column(String, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # Webhook-spezifisch
    hashed_token = Column(String, unique=True, nullable=True, index=True)

    # Event-spezifisch: JSON-Array als String, z. B. '["connection.created"]'
    event_triggers = Column(String, nullable=True)

    # Schedule-spezifisch
    schedule_interval = Column(String, nullable=True)  # "5m", "1h", … oder Cron
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)


# Alte Tabelle bleibt für bestehende DBs erhalten (wird nicht mehr aktiv genutzt)
class WebhookScript(Base):
    __tablename__ = "webhook_scripts"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    hashed_token = Column(String, unique=True, nullable=False)
    script = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
