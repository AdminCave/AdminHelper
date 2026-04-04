"""
Reverse-Proxy: Leitet /api/monitoring/* Anfragen an den Monitoring-Service weiter.

Der Browser kommuniziert nur mit dem SRM-Server. Monitoring-Anfragen werden
intern im Docker-Netzwerk an den Monitoring-Container weitergeleitet.
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, Request, Response

from app.core.auth import get_current_admin

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

MONITOR_SERVICE_URL = os.environ.get("MONITOR_SERVICE_URL", "http://monitoring:8080")
MONITOR_API_KEY = os.environ.get("MONITOR_API_KEY", "")


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_monitoring(path: str, request: Request, _admin=Depends(get_current_admin)):
    """Proxy fuer alle Monitoring-Anfragen (nur fuer Admins)."""
    async with httpx.AsyncClient(timeout=30) as client:
        target_url = f"{MONITOR_SERVICE_URL}/{path}"
        resp = await client.request(
            method=request.method,
            url=target_url,
            content=await request.body(),
            headers={"X-Internal-Key": MONITOR_API_KEY},
            params=request.query_params,
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )
