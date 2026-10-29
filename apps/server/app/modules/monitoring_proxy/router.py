# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Reverse proxy: forwards /api/monitoring/* requests to the monitoring service.

The browser communicates only with the AdminHelper server. Monitoring requests
are forwarded internally within the Docker network to the monitoring container.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.auth import get_current_admin
from app.core.config import MONITOR_API_KEY, MONITOR_SERVICE_URL
from app.core.database import get_db
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT, require_cert_server, require_scope
from app.core.middleware import resolve_client_ip
from app.core.rate_limit import get_backend
from app.core.request_context import actor_from_request
from app.modules.audit import service as audit

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

logger = logging.getLogger(__name__)


def _upstream_error(route: str, exc: httpx.HTTPError) -> HTTPException:
    """The answer for a forward the monitoring service did not answer: 504 for a timeout,
    502 for anything else. Logged with the type only: the message carries the URL."""
    logger.warning("monitoring proxy (%s): %s", route, type(exc).__name__)
    if isinstance(exc, httpx.TimeoutException):
        return HTTPException(status_code=504, detail="monitoring service timed out")
    return HTTPException(status_code=502, detail="monitoring service unreachable")


# The agent-report ingest is public (X-API-Key, no JWT). Cap per-IP so an
# unauthenticated flood can't drive the proxy-forward + monitoring auth path.
# Generous for legit agents (they report ~once/minute).
_INGEST_MAX = 120
_INGEST_WINDOW = 60

# Normalize once: a trailing slash would make the forwards below emit a double
# slash (http://monitoring:8080//agent/...), which the no-prefix monitoring
# routes do NOT match -> 404. Mirrors the rstrip in provisioning/helpers.py.
_MONITOR_BASE = MONITOR_SERVICE_URL.rstrip("/")

# Reuse one async client across proxy forwards instead of a fresh AsyncClient (TCP handshake + pool
# setup) per request — agent reports arrive every minute per server. httpx binds its pools lazily, so
# building it at import is safe; the app lifespan closes it on shutdown (5.30) and calls
# open_client() on startup.
_client = httpx.AsyncClient(timeout=30)


def open_client() -> None:
    """Replace a closed proxy client with a new one; leave an open one alone.

    A closed client refuses every request, so a second lifespan in the same process (a
    re-entered TestClient, the schemathesis transport) would otherwise run on the client the
    previous shutdown closed (R-0376). An open one stays: a test may have installed a stub
    before the lifespan starts (monitoring_stub in tests/test_schemathesis.py). Production runs
    one lifespan per process, so there this is a no-op.
    """
    global _client
    if _client.is_closed:
        _client = httpx.AsyncClient(timeout=30)


# Allowed path prefixes for the monitoring proxy (SSRF protection)
_ALLOWED_PATH_PREFIXES = (
    "checks",
    "alerts",
    "status",
    "templates",
    "maintenance",
    "agent",
)

# Raised before the request left this process: the monitoring received nothing.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol)


async def _audit_write(db: Session, request: Request, path: str, status: str, detail: str) -> None:
    """One audit row for a forwarded write (none for GET); the request body never lands in it."""
    if request.method == "GET":
        return
    await run_in_threadpool(
        audit.record,
        db,
        f"monitoring.{request.method.lower()}",
        object_type="monitoring",
        object_label=path,
        status=status,
        detail=detail,
        actor=actor_from_request(request),
    )


@router.post("/agent/{server_id}/report", dependencies=[Depends(require_cert_server)])
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
    # `server_id` is percent-DECODED by Starlette: re-encode it, or a '?'/'#' truncates the
    # target URL (another monitoring route) and a control character makes httpx raise InvalidURL.
    try:
        resp = await _client.post(
            f"{_MONITOR_BASE}/agent/{quote(server_id, safe='')}/report",
            content=await request.body(),
            headers={
                "X-API-Key": request.headers.get("x-api-key", ""),
                "Content-Type": request.headers.get("content-type", "application/json"),
            },
        )
    except httpx.HTTPError as exc:
        raise _upstream_error("agent report", exc) from None
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type"),
    )


# One decorator per method instead of a single api_route(methods=[…]): FastAPI
# derives an operation's operationId from `list(route.methods)[0]`, so a
# multi-method route gives all four operations ONE id — picked from a set, i.e.
# a different one per process (string hashing is randomized), and duplicated
# across four operations, which OpenAPI forbids. Four routes give four stable,
# unique ids. Routing is unchanged and so is the 405 status; the one visible
# difference is that Starlette builds the `Allow` header from the first partially
# matching route, so it now names one method instead of all four. No client in
# this repo reads it (checked: apps/web, apps/desktop/ui, apps/agent). Without
# this the generated schema differs between runs and tests/openapi.snapshot.json
# could never be pinned (harness 8a, T7).
@router.get("/{path:path}")
@router.post("/{path:path}")
@router.put("/{path:path}")
@router.delete("/{path:path}")
async def proxy_to_monitoring(
    path: str,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
    _scope=Depends(require_scope(SCOPE_ACCESS)),
):
    """Proxy for all monitoring requests (admins only)."""
    # Prevent path traversal and SSRF: allow only known paths
    normalized = path.lstrip("/")
    if ".." in normalized or not any(normalized.startswith(p) for p in _ALLOWED_PATH_PREFIXES):
        raise HTTPException(status_code=400, detail="Unerlaubter Proxy-Pfad")

    # Forward the still-encoded wire path: `path` is percent-DECODED by
    # Starlette, so re-embedding it would let '#'/'?' in a segment (e.g. a tag
    # name like "web#1") truncate the target URL as fragment/query (T41). The
    # guard above stays on the decoded form ('%2e%2e' is caught there too).
    raw = request.scope.get("raw_path", b"")
    raw_path = raw.decode("ascii", errors="replace") if isinstance(raw, bytes) else str(raw)
    prefix = "/api/monitoring/"
    if raw_path.startswith(prefix):
        forward_path = raw_path[len(prefix) :]
    else:
        forward_path = quote(path, safe="/")

    target_url = f"{_MONITOR_BASE}/{forward_path}"
    try:
        resp = await _client.request(
            method=request.method,
            url=target_url,
            content=await request.body(),
            headers={
                "X-Internal-Key": MONITOR_API_KEY,
                "Content-Type": request.headers.get("content-type", "application/json"),
            },
            params=request.query_params,
        )
    except httpx.HTTPError as exc:
        # A connection error means nothing was sent. An error after sending may hide a change
        # the monitoring already applied, hence an `error` row. Only the type name: the
        # message carries the target URL.
        if not isinstance(exc, _NOT_SENT):
            await _audit_write(db, request, forward_path, "error", f"error={type(exc).__name__}")
        raise _upstream_error("admin proxy", exc) from None
    await _audit_write(
        db,
        request,
        forward_path,
        "success" if resp.status_code < 400 else "failure",
        f"status={resp.status_code}",
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
