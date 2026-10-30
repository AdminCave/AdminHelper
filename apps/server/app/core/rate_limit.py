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
from urllib.parse import urlsplit

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
            logger.warning(
                "Redis get failed (%s), falling back to in-memory: %s", key, type(e).__name__
            )
            return self._fallback.get_count(key)

    def increment(self, key: str, window_seconds: int) -> int:
        try:
            pipe = self._client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            result = pipe.execute()
            return int(result[0])
        except Exception as e:
            logger.warning(
                "Redis incr failed (%s), falling back to in-memory: %s", key, type(e).__name__
            )
            return self._fallback.increment(key, window_seconds)

    def reset(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception as e:
            logger.warning("Redis del failed (%s): %s", key, type(e).__name__)
        self._fallback.reset(key)


_backend: RateLimitBackend | None = None
# When the initial Redis connect fails (Redis boots a few seconds after the server, a brief blip),
# retry after a cooldown instead of pinning the In-Memory fallback forever — under multiple workers
# a permanent fallback counts the limit per-worker instead of globally until the next deploy (4.133).
_next_redis_retry = 0.0
_REDIS_RETRY_COOLDOWN = 60.0


def _redis_target(url: str) -> str:
    """Scheme, host and port of a Redis URL (for `unix://` the socket path) for the log. A Redis
    URL carries credentials in the netloc or as a query parameter (redis-py passes unknown query
    names on as connection arguments), so nothing else of it is logged — like `_log_host` in the
    monitoring alerter."""
    try:
        parts = urlsplit(url)
        if parts.scheme == "unix":
            return f"unix://{parts.path}" if parts.path else "?"
        if not parts.hostname:
            return "?"
        port = parts.port
    except ValueError:
        # urlsplit raises on a malformed IPv6 literal, .port on a port that is no number or out of
        # range.
        return "?"
    # An IPv6 literal keeps its brackets, or its colons run into the port.
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    target = f"{parts.scheme}://{host}"
    return f"{target}:{port}" if port is not None else target


def get_backend() -> RateLimitBackend:
    global _backend, _next_redis_retry
    # A live Redis backend is kept for good; an In-Memory fallback is retried once the cooldown
    # elapses, so a transiently-unreachable Redis is adopted when it returns.
    if isinstance(_backend, RedisBackend):
        return _backend
    if _backend is not None and time.monotonic() < _next_redis_retry:
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
            logger.info("Rate limit uses Redis (%s)", _redis_target(REDIS_URL))
            return _backend
        except ImportError:
            # redis-py absent doesn't change at runtime — stop retrying.
            logger.warning("redis-py is not installed — falling back to the in-memory rate limit")
            _next_redis_retry = float("inf")
        except Exception as e:
            logger.warning(
                "Redis unreachable (%s) — in-memory rate limit, retry in %.0fs: %s",
                _redis_target(REDIS_URL),
                _REDIS_RETRY_COOLDOWN,
                type(e).__name__,
            )
            _next_redis_retry = time.monotonic() + _REDIS_RETRY_COOLDOWN
    else:
        # No REDIS_URL: In-Memory is the intended backend (single-worker), don't retry.
        _next_redis_retry = float("inf")

    if _backend is None:
        _backend = InMemoryBackend()
        logger.info("Rate limit uses in-memory counters")
    return _backend


def reset_backend_for_tests() -> None:
    """For tests only: forces re-initialization on the next get_backend()."""
    global _backend, _next_redis_retry
    _backend = None
    _next_redis_retry = 0.0
