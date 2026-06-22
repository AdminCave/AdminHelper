# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-worker SSE stream registry + cross-worker fan-out via Redis Pub/Sub.

Each web worker keeps a local registry ``{user_id: set[asyncio.Queue]}`` of its
connected SSE streams plus one Redis subscription (started in the lifespan).
After ingest_event commits, it publishes a lightweight refresh signal to a
global channel; every worker's reader delivers it to its locally connected
streams of the affected users, which makes the desktop bell reload the feed.

The payload is only a "refresh" nudge (with the highest new notification id) —
the client pulls the actual rows via the existing REST endpoint, so there is no
second serialization/authorization path and no risk of leaking another user's
data over the wire. Without REDIS_URL there is no push (the client's polling
fallback covers it); we never touch the asyncio.Queue from the sync ingest
thread, only from the async reader on the event loop.
"""

import asyncio
import json
import logging
from collections import defaultdict

logger = logging.getLogger("adminhelper.notifications.stream")

CHANNEL = "notif:events"
# Bounded so a stuck consumer cannot grow memory without limit; on overflow we
# drop the refresh nudge (the client's poll fallback reconciles).
_QUEUE_MAXSIZE = 32

_subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)

_redis = None
_reader_task: asyncio.Task | None = None


def register(user_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _subscribers[user_id].add(q)
    return q


def unregister(user_id: int, q: asyncio.Queue) -> None:
    streams = _subscribers.get(user_id)
    if not streams:
        return
    streams.discard(q)
    if not streams:
        _subscribers.pop(user_id, None)


def deliver_local(user_id: int, payload: str) -> None:
    """Push a refresh payload to every locally connected stream of this user."""
    for q in list(_subscribers.get(user_id, ())):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.debug("SSE queue full for user %s — dropping refresh", user_id)


def publish(user_ids, max_id: int) -> None:
    """Publish a refresh signal for the given users. Called from the sync ingest
    path, so it uses the synchronous redis client (same as rate_limit)."""
    from app.core.config import REDIS_URL

    if not REDIS_URL or not user_ids:
        return
    try:
        import redis

        client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        client.publish(CHANNEL, json.dumps({"user_ids": list(user_ids), "maxId": max_id}))
    except Exception:
        logger.warning("SSE fan-out publish failed — clients fall back to polling", exc_info=True)


async def start(redis_url: str) -> None:
    """Start this worker's Redis subscription + reader task (lifespan, once)."""
    global _redis, _reader_task
    if not redis_url:
        logger.info("REDIS_URL not set — SSE push disabled (polling fallback only)")
        return
    import redis.asyncio as aioredis

    _redis = aioredis.from_url(redis_url, socket_connect_timeout=2)
    pubsub = _redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    _reader_task = asyncio.create_task(_reader(pubsub))
    logger.info("SSE fan-out subscribed to Redis channel %s", CHANNEL)


async def _reader(pubsub) -> None:
    try:
        while True:
            # timeout keeps the loop responsive to cancellation at shutdown.
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None:
                continue
            try:
                data = json.loads(msg["data"])
            except (ValueError, TypeError):
                continue
            payload = json.dumps({"type": "refresh", "maxId": data.get("maxId", 0)})
            for uid in data.get("user_ids", ()):
                deliver_local(int(uid), payload)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("SSE Redis reader crashed")


async def stop() -> None:
    """Cancel the reader and close the Redis connection (lifespan shutdown)."""
    global _reader_task, _redis
    if _reader_task:
        _reader_task.cancel()
        try:
            await _reader_task
        except asyncio.CancelledError:
            pass
        _reader_task = None
    if _redis:
        await _redis.aclose()  # explicit close required for asyncio Redis
        _redis = None
