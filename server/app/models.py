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


class WebhookScript(Base):
    __tablename__ = "webhook_scripts"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    hashed_token = Column(String, unique=True, nullable=False)
    script = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
