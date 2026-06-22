# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SSE endpoint for the notification bell: GET /api/notifications/stream.

A long-lived text/event-stream that pushes a "refresh" nudge whenever the caller
gets a new notification (the client then pulls the feed via REST). The handler is
async and DB-free — it only reads from its asyncio.Queue — so it never blocks the
worker event loop (the rest of the stack is sync SQLAlchemy). Cross-worker
delivery is handled by stream_hub via Redis Pub/Sub.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.modules.notifications import stream_hub

stream_router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# Heartbeat comment cadence — keeps the stream under nginx's proxy_read_timeout.
_HEARTBEAT_SECS = 15


def authenticate_stream_user(request: Request) -> int:
    """Auth for the SSE stream. Validates the bearer JWT with a SHORT-LIVED
    session and returns the user id. We deliberately do NOT use
    Depends(get_current_user): that holds the get_db session for the whole
    response, and an SSE response lives for minutes/hours — one DB connection per
    open stream would exhaust the pool. Here the session is opened and closed
    immediately, before the stream starts."""
    from app.core.auth import _get_user_from_token
    from app.core.database import SessionLocal

    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    db = SessionLocal()
    try:
        user = _get_user_from_token(token, db) if token else None
    finally:
        db.close()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nicht authentifiziert",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user.id


@stream_router.get("/stream")
async def notification_stream(
    request: Request,
    user_id: int = Depends(authenticate_stream_user),
):
    queue = stream_hub.register(user_id)

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # heartbeat against proxy_read_timeout
                    continue
                yield f"event: notification\ndata: {payload}\n\n"
        finally:
            # Runs on client disconnect (CancelledError) too — no registry leak.
            stream_hub.unregister(user_id, queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx response buffering
            "Connection": "keep-alive",
        },
    )
