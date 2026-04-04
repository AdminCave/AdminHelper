from fastapi import Depends, HTTPException, Request, status

from app.core.config import AGENT_API_KEYS, INTERNAL_API_KEY


def require_internal(request: Request) -> None:
    """Validiert den internen API-Key (SRM-Proxy -> Monitoring)."""
    key = request.headers.get("X-Internal-Key", "")
    if not key or key != INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger interner API-Key")


def require_agent(request: Request) -> None:
    """Validiert den Agent API-Key (Remote-Server -> Monitoring)."""
    key = request.headers.get("X-API-Key", "")
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API-Key fehlt")
    # Akzeptiere sowohl Agent-Keys als auch den internen Key
    if key != INTERNAL_API_KEY and key not in AGENT_API_KEYS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger API-Key")
