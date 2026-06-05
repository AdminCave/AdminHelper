# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rate-limit backend with Redis and an in-memory fallback.

Redis is required as soon as the server runs with multiple worker processes
(`uvicorn --workers N`), because otherwise each worker has a separate
counter and the limit is effectively multiplied by N. Without REDIS_URL the
module falls back to an in-memory counter (suitable only for
single-worker / dev setups).

Scheme: fixed window per key. INCR + EXPIRE NX in a single pipeline ensures
the TTL is set only on the first hit; otherwise an attacker could extend the
block state by sustained fire.
"""

import logging
import time
from collections import defaultdict
from typing import Protocol

logger = logging.getLogger("adminhelper.rate_limit")


class RateLimitBackend(Protocol):
    def get_count(self, key: str) -> int: ...
    def increment(self, key: str, window_seconds: int) -> int: ...
    def reset(self, key: str) -> None: ...


class InMemoryBackend:
    def __init__(self) -> None:
        self._counters: dict[str, tuple[int, float]] = {}
        self._last_cleanup = 0.0
        self._cleanup_interval = 300.0

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup <= self._cleanup_interval:
            return
        self._last_cleanup = now
        stale = [k for k, (_, exp) in self._counters.items() if now >= exp]
        for k in stale:
            del self._counters[k]

    def get_count(self, key: str) -> int:
        now = time.monotonic()
        self._cleanup(now)
        entry = self._counters.get(key)
        if entry is None or now >= entry[1]:
            return 0
        return entry[0]

    def increment(self, key: str, window_seconds: int) -> int:
        now = time.monotonic()
        self._cleanup(now)
        entry = self._counters.get(key)
        if entry is None or now >= entry[1]:
            count = 1
            self._counters[key] = (count, now + window_seconds)
        else:
            count = entry[0] + 1
            self._counters[key] = (count, entry[1])
        return count

    def reset(self, key: str) -> None:
        self._counters.pop(key, None)


class RedisBackend:
    def __init__(self, client) -> None:
        self._client = client

    def get_count(self, key: str) -> int:
        try:
            value = self._client.get(key)
            return int(value) if value else 0
        except Exception as e:
            logger.warning("Redis get fehlgeschlagen (%s) — Limit nicht durchgesetzt: %s", key, e)
            return 0

    def increment(self, key: str, window_seconds: int) -> int:
        try:
            pipe = self._client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            result = pipe.execute()
            return int(result[0])
        except Exception as e:
            logger.warning("Redis incr fehlgeschlagen (%s): %s", key, e)
            return 0

    def reset(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception as e:
            logger.warning("Redis del fehlgeschlagen (%s): %s", key, e)


_backend: RateLimitBackend | None = None


def get_backend() -> RateLimitBackend:
    global _backend
    if _backend is not None:
        return _backend

    from app.core.config import REDIS_URL

    if REDIS_URL:
        try:
            import redis

            client = redis.Redis.from_url(
                REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=False,
            )
            client.ping()
            _backend = RedisBackend(client)
            logger.info("Rate-Limit nutzt Redis (%s)", REDIS_URL)
            return _backend
        except ImportError:
            logger.warning("redis-py nicht installiert — fallback auf In-Memory-Rate-Limit")
        except Exception as e:
            logger.warning("Redis nicht erreichbar (%s) — fallback auf In-Memory: %s", REDIS_URL, e)

    _backend = InMemoryBackend()
    logger.info("Rate-Limit nutzt In-Memory (Single-Worker-Setup)")
    return _backend


def reset_backend_for_tests() -> None:
    """For tests only: forces re-initialization on the next get_backend()."""
    global _backend
    _backend = None
