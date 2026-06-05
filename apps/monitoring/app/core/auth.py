# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import secrets

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import INTERNAL_API_KEY
from app.core.database import get_db


def _key_matches(provided: str | None, expected: str) -> bool:
    """Constant-time key comparison. Fails closed when no key is configured
    (an empty expected key must never authenticate). Compares bytes so a
    non-ASCII header can't raise inside compare_digest, and tolerates a None
    provided value (returns False) rather than raising."""
    return bool(expected) and secrets.compare_digest((provided or "").encode(), expected.encode())


def require_internal(request: Request) -> None:
    """Validates the internal API key (AdminHelper proxy -> Monitoring)."""
    key = request.headers.get("X-Internal-Key", "")
    if not _key_matches(key, INTERNAL_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger interner API-Key")


def require_agent(request: Request, db: Session = Depends(get_db)) -> str:
    """Validates the agent API key against the DB. Returns the server_id."""
    from app.models import MonitorAgentKey

    key = request.headers.get("X-API-Key", "")
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API-Key fehlt")

    # Internal key has access to all servers (constant-time, fails closed)
    if _key_matches(key, INTERNAL_API_KEY):
        return "__internal__"

    # Hash the agent key and compare against the DB
    hashed = MonitorAgentKey.hash_key(key)
    agent_key = db.query(MonitorAgentKey).filter(MonitorAgentKey.hashed_key == hashed).first()
    if not agent_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger API-Key")

    return agent_key.server_id
