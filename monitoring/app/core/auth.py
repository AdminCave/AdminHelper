from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import INTERNAL_API_KEY
from app.core.database import get_db


def require_internal(request: Request) -> None:
    """Validiert den internen API-Key (SRM-Proxy -> Monitoring)."""
    key = request.headers.get("X-Internal-Key", "")
    if not key or key != INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger interner API-Key")


def require_agent(request: Request, db: Session = Depends(get_db)) -> str:
    """Validiert den Agent API-Key gegen die DB. Gibt die server_id zurueck."""
    from app.models import MonitorAgentKey

    key = request.headers.get("X-API-Key", "")
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API-Key fehlt")

    # Interner Key hat Zugriff auf alle Server
    if key == INTERNAL_API_KEY:
        return "__internal__"

    # Agent-Key hashen und gegen DB vergleichen
    hashed = MonitorAgentKey.hash_key(key)
    agent_key = db.query(MonitorAgentKey).filter(MonitorAgentKey.hashed_key == hashed).first()
    if not agent_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger API-Key")

    return agent_key.server_id
