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
import threading
import time
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
        # Sync endpoints (login/bootstrap/hook-trigger) run in the FastAPI threadpool, so
        # increment/get_count/reset are called concurrently. Guard every _counters access: else
        # _cleanup's iteration races an insert (RuntimeError: dict changed size during iteration,
        # a 500 in login) and the read-modify-write loses brute-force counts (4.66). _cleanup runs
        # under the caller's lock — the Lock is non-reentrant, so it must not re-acquire.
        self._lock = threading.Lock()

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup <= self._cleanup_interval:
            return
        self._last_cleanup = now
        stale = [k for k, (_, exp) in self._counters.items() if now >= exp]
        for k in stale:
            del self._counters[k]

    def get_count(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            entry = self._counters.get(key)
            if entry is None or now >= entry[1]:
                return 0
            return entry[0]

    def increment(self, key: str, window_seconds: int) -> int:
        now = time.monotonic()
        with self._lock:
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
        with self._lock:
            self._counters.pop(key, None)


class RedisBackend:
    def __init__(self, client) -> None:
        self._client = client
        # On a Redis outage we must NOT fail open (returning 0 silently disabled
        # the brute-force/abuse limit for the whole outage). Degrade to a local
        # in-memory counter instead: the limit stays enforced (per-worker), just
        # not shared across workers — acceptable, and the server is single-worker
        # by default anyway.
        self._fallback = InMemoryBackend()

    def get_count(self, key: str) -> int:
        try:
            value = self._client.get(key)
            return int(value) if value else 0
        except Exception as e:
            logger.warning("Redis get fehlgeschlagen (%s) — degradiere auf In-Memory: %s", key, e)
            return self._fallback.get_count(key)

    def increment(self, key: str, window_seconds: int) -> int:
        try:
            pipe = self._client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            result = pipe.execute()
            return int(result[0])
        except Exception as e:
            logger.warning("Redis incr fehlgeschlagen (%s) — degradiere auf In-Memory: %s", key, e)
            return self._fallback.increment(key, window_seconds)

    def reset(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception as e:
            logger.warning("Redis del fehlgeschlagen (%s): %s", key, e)
        self._fallback.reset(key)


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
