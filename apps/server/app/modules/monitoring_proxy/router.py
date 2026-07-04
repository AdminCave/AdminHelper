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
from starlette.concurrency import run_in_threadpool

from app.core.auth import get_current_admin
from app.core.config import MONITOR_API_KEY, MONITOR_SERVICE_URL
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT, require_scope
from app.core.middleware import resolve_client_ip
from app.core.rate_limit import get_backend

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

# The agent-report ingest is public (X-API-Key, no JWT). Cap per-IP so an
# unauthenticated flood can't drive the proxy-forward + monitoring auth path.
# Generous for legit agents (they report ~once/minute).
_INGEST_MAX = 120
_INGEST_WINDOW = 60

# Normalize once: a trailing slash would make the forwards below emit a double
# slash (http://monitoring:8080//agent/...), which the no-prefix monitoring
# routes do NOT match -> 404. Mirrors the rstrip in provisioning/helpers.py.
_MONITOR_BASE = MONITOR_SERVICE_URL.rstrip("/")

# Allowed path prefixes for the monitoring proxy (SSRF protection)
_ALLOWED_PATH_PREFIXES = (
    "checks",
    "alerts",
    "log",
    "metrics",
    "status",
    "templates",
    "agent",
)


@router.post("/agent/{server_id}/report")
async def proxy_agent_report(
    server_id: str,
    request: Request,
    _scope=Depends(require_scope(SCOPE_AGENT)),
):
    """Proxy for agent reports (auth via X-API-Key, no JWT needed; agent scope)."""
    ip = resolve_client_ip(request)
    # The backend may be Redis (a blocking socket call); offload it so it does
    # not stall the event loop on the single-worker backend (mirrors hooks/router).
    count = await run_in_threadpool(get_backend().increment, f"agent_ingest:{ip}", _INGEST_WINDOW)
    if count > _INGEST_MAX:
        raise HTTPException(status_code=429, detail="Zu viele Agent-Reports")
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
async def proxy_to_monitoring(
    path: str,
    request: Request,
    _admin=Depends(get_current_admin),
    _scope=Depends(require_scope(SCOPE_ACCESS)),
):
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
        # Forward the pagination total — the proxy otherwise strips response
        # headers, which would make X-Total-Count unreachable for the UI.
        extra_headers = (
            {"X-Total-Count": resp.headers["x-total-count"]}
            if "x-total-count" in resp.headers
            else None
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
            headers=extra_headers,
        )
