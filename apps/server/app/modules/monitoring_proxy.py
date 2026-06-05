# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Reverse proxy: forwards /api/monitoring/* requests to the monitoring service.

The browser communicates only with the AdminHelper server. Monitoring requests
are forwarded internally within the Docker network to the monitoring container.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.auth import get_current_admin
from app.core.config import MONITOR_SERVICE_URL, MONITOR_API_KEY

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

# Normalize once: a trailing slash would make the forwards below emit a double
# slash (http://monitoring:8080//agent/...), which the no-prefix monitoring
# routes do NOT match -> 404. Mirrors the rstrip in provisioning/helpers.py.
_MONITOR_BASE = MONITOR_SERVICE_URL.rstrip("/")

# Allowed path prefixes for the monitoring proxy (SSRF protection)
_ALLOWED_PATH_PREFIXES = (
    "checks", "alerts", "log", "metrics", "status",
    "templates", "agent",
)


@router.post("/agent/{server_id}/report")
async def proxy_agent_report(server_id: str, request: Request):
    """Proxy for agent reports (auth via X-API-Key, no JWT needed)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_MONITOR_BASE}/agent/{server_id}/report",
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
    """Proxy for all monitoring requests (admins only)."""
    # Prevent path traversal and SSRF: allow only known paths
    normalized = path.lstrip("/")
    if ".." in normalized or not any(normalized.startswith(p) for p in _ALLOWED_PATH_PREFIXES):
        raise HTTPException(status_code=400, detail="Unerlaubter Proxy-Pfad")

    async with httpx.AsyncClient(timeout=30) as client:
        target_url = f"{_MONITOR_BASE}/{path}"
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
