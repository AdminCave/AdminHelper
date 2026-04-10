"""
Reverse-Proxy: Leitet /api/monitoring/* Anfragen an den Monitoring-Service weiter.

Der Browser kommuniziert nur mit dem AdminHelper-Server. Monitoring-Anfragen werden
intern im Docker-Netzwerk an den Monitoring-Container weitergeleitet.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.auth import get_current_admin
from app.core.config import MONITOR_SERVICE_URL, MONITOR_API_KEY

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

# Erlaubte Pfad-Prefixe fuer den Monitoring-Proxy (SSRF-Schutz)
_ALLOWED_PATH_PREFIXES = (
    "checks", "alerts", "log", "metrics", "status",
    "templates", "agent",
)


@router.post("/agent/{server_id}/report")
async def proxy_agent_report(server_id: str, request: Request):
    """Proxy fuer Agent-Reports (Auth via X-API-Key, kein JWT noetig)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{MONITOR_SERVICE_URL}/agent/{server_id}/report",
            content=await request.body(),
            headers={
                "X-API-Key": request.headers.get("x-api-key", ""),
                "Content-Type": request.headers.get("content-type", "application/json"),
            },
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_monitoring(path: str, request: Request, _admin=Depends(get_current_admin)):
    """Proxy fuer alle Monitoring-Anfragen (nur fuer Admins)."""
    # Path-Traversal und SSRF verhindern: nur bekannte Pfade erlauben
    normalized = path.lstrip("/")
    if ".." in normalized or not any(normalized.startswith(p) for p in _ALLOWED_PATH_PREFIXES):
        raise HTTPException(status_code=400, detail="Unerlaubter Proxy-Pfad")

    async with httpx.AsyncClient(timeout=30) as client:
        target_url = f"{MONITOR_SERVICE_URL}/{path}"
        resp = await client.request(
            method=request.method,
            url=target_url,
            content=await request.body(),
            headers={
                "X-Internal-Key": MONITOR_API_KEY,
                "Content-Type": request.headers.get("content-type", "application/json"),
            },
            params=request.query_params,
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )
