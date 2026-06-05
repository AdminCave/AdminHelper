# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent key management and server cleanup."""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_internal
from app.core.database import get_db
from app.models import MonitorAgentKey
from app.template_sync import cleanup_server

router = APIRouter()


@router.post("/agent-keys/{server_id}", dependencies=[Depends(require_internal)])
def create_agent_key(server_id: str, db: Session = Depends(get_db)):
    """Generates a new agent API key for a server.

    The raw key is only returned on creation. For an existing key it must be
    regenerated (DELETE + POST).
    """
    # If a key exists: delete the old one and regenerate
    existing = db.query(MonitorAgentKey).filter(MonitorAgentKey.server_id == server_id).first()
    if existing:
        db.delete(existing)
        db.flush()

    raw_key = secrets.token_urlsafe(48)
    key = MonitorAgentKey(
        id=str(uuid.uuid4()),
        server_id=server_id,
        hashed_key=MonitorAgentKey.hash_key(raw_key),
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    d = key.to_dict()
    d["apiKey"] = raw_key  # Return the raw key once
    return d


@router.delete("/agent-keys/{server_id}", dependencies=[Depends(require_internal)])
def delete_agent_key(server_id: str, db: Session = Depends(get_db)):
    """Deletes the agent API key of a server."""
    db.query(MonitorAgentKey).filter(MonitorAgentKey.server_id == server_id).delete()
    db.commit()
    return {"deleted": True}


@router.delete("/servers/{server_id}/cleanup", dependencies=[Depends(require_internal)])
def server_cleanup(server_id: str, db: Session = Depends(get_db)):
    """Cleans up all monitoring data of a server."""
    result = cleanup_server(db, server_id)
    return result
