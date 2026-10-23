# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""InMemoryBackend thread-safety (4.66): sync endpoints (login/bootstrap/hook-trigger) run in
the FastAPI threadpool, so the backend is hit from many threads at once. The Redis backend's
log lines name only scheme, host and port of REDIS_URL and only the type of an error."""

import logging
import sys
import threading
import types

import pytest

import app.core.config as config
import app.core.rate_limit as rl
from app.core.rate_limit import InMemoryBackend

# Credentials in the netloc and as a query parameter (redis-py passes unknown query names on
# as connection arguments).
_SECRET_REDIS_URL = "redis://hookuser:s3cr3t-pw@redis.example:6380/0?password=q5ecret"
_URL_SECRETS = ("hookuser", "s3cr3t-pw", "q5ecret")


@pytest.fixture()
def fake_redis(monkeypatch):
    """A stand-in redis module: ping fails while state["ping_ok"] is false (ConnectionError
    "Redis down"); state["urls"] records what from_url got."""
    rl.reset_backend_for_tests()
    monkeypatch.setattr(config, "REDIS_URL", _SECRET_REDIS_URL, raising=False)
    state = {"ping_ok": False, "urls": []}

    class _FakeClient:
        def ping(self):
            if not state["ping_ok"]:
                raise ConnectionError("Redis down")

    def from_url(url, **kwargs):
        state["urls"].append(url)
        return _FakeClient()

    fake_module = types.ModuleType("redis")
    fake_module.Redis = types.SimpleNamespace(from_url=from_url)
    monkeypatch.setitem(sys.modules, "redis", fake_module)
    try:
        yield state
    finally:
        rl.reset_backend_for_tests()


def test_increment_thread_safe_no_lost_counts_or_cleanup_race():
    # 4.66: force _cleanup on every call (interval 0) to expose the dict-changed-size-during-
    # iteration race, and hammer a shared key from many threads to expose the lost
    # read-modify-write. Lock-guarded, this must not raise and must not lose a single increment.
    backend = InMemoryBackend()
    backend._cleanup_interval = 0.0
    threads_n, per_thread = 8, 400

    def worker(tid):
        for i in range(per_thread):
            backend.increment("shared", 60)
            # Unique keys per thread so the dict grows large -> _cleanup's list-comprehension
            # iterates a big dict while other threads insert (the dict-changed-size race).
            backend.increment(f"t{tid}-k{i}", 60)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert backend.get_count("shared") == threads_n * per_thread


def test_redis_fallback_retries_after_cooldown(monkeypatch):
    # 4.133: a failed initial Redis connect falls back to In-Memory but retries after the cooldown,
    # rather than pinning the In-Memory backend forever (which counts per-worker under N workers).
    import sys
    import types

    import app.core.config as config
    import app.core.rate_limit as rl
    from app.core.rate_limit import InMemoryBackend, RedisBackend

    rl.reset_backend_for_tests()
    monkeypatch.setattr(config, "REDIS_URL", "redis://localhost:6379/0", raising=False)

    state = {"ping_ok": False}

    class _FakeClient:
        def ping(self):
            if not state["ping_ok"]:
                raise ConnectionError("Redis down")

    fake_redis = types.ModuleType("redis")
    fake_redis.Redis = types.SimpleNamespace(from_url=lambda *a, **k: _FakeClient())
    monkeypatch.setitem(sys.modules, "redis", fake_redis)

    fake_time = {"now": 1000.0}
    monkeypatch.setattr(rl.time, "monotonic", lambda: fake_time["now"])

    # 1) Redis down -> In-Memory fallback.
    b1 = rl.get_backend()
    assert isinstance(b1, InMemoryBackend)

    # 2) Redis back, but still within the cooldown -> stays on the same In-Memory backend.
    state["ping_ok"] = True
    fake_time["now"] = 1030.0
    assert rl.get_backend() is b1

    # 3) After the cooldown -> Redis adopted.
    fake_time["now"] = 1070.0
    assert isinstance(rl.get_backend(), RedisBackend)

    rl.reset_backend_for_tests()


def test_login_check_rate_limit_increments_atomically():
    # 4.141: _check_rate_limit must INCREMENT (atomic) up front, not just read the count and let the
    # increment happen only after a failed verify — else N parallel logins all see count=0, all pass
    # and all run bcrypt, bypassing the limit. After _MAX_ATTEMPTS calls the next raises 429.
    import pytest
    from fastapi import HTTPException

    import app.modules.users.auth_router as ar
    from app.core.rate_limit import reset_backend_for_tests

    reset_backend_for_tests()
    try:
        ip = "203.0.113.7"
        for _ in range(ar._MAX_ATTEMPTS):
            ar._check_rate_limit(ip)  # each call increments; all within the limit
        with pytest.raises(HTTPException) as exc:
            ar._check_rate_limit(ip)  # one over -> 429
        assert exc.value.status_code == 429
    finally:
        reset_backend_for_tests()


def test_unreachable_redis_logs_only_its_target_and_the_error_type(fake_redis, caplog):
    with caplog.at_level(logging.INFO, logger=rl.logger.name):
        backend = rl.get_backend()

    assert isinstance(backend, InMemoryBackend)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "redis://redis.example:6380" in message
    assert "ConnectionError" in message
    for leaked in (*_URL_SECRETS, "Redis down"):
        assert leaked not in caplog.text
    assert not any(r.exc_info for r in caplog.records)
    # The connection itself still gets the whole URL.
    assert fake_redis["urls"] == [_SECRET_REDIS_URL]


def test_reachable_redis_logs_only_its_target(fake_redis, caplog):
    fake_redis["ping_ok"] = True
    with caplog.at_level(logging.INFO, logger=rl.logger.name):
        backend = rl.get_backend()

    assert isinstance(backend, rl.RedisBackend)
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 1
    assert "redis://redis.example:6380" in infos[0].getMessage()
    for leaked in _URL_SECRETS:
        assert leaked not in caplog.text
    assert fake_redis["urls"] == [_SECRET_REDIS_URL]


@pytest.mark.parametrize(
    ("url", "target"),
    [
        (_SECRET_REDIS_URL, "redis://redis.example:6380"),
        ("rediss://redis.example", "rediss://redis.example"),
        ("unix:///run/redis.sock?password=q5ecret", "unix:///run/redis.sock"),
        ("unix://hookuser:s3cr3t-pw@/run/redis.sock", "unix:///run/redis.sock"),
        # A port that is no number: .port raises ValueError.
        ("redis://u:p@redis.example:notaport/0", "?"),
        # A malformed IPv6 literal: urlsplit itself raises ValueError.
        ("redis://u:p@[::1/0", "?"),
        # No host.
        ("redis://u:p@/0", "?"),
    ],
)
def test_redis_target_keeps_only_scheme_host_and_port(url, target):
    assert rl._redis_target(url) == target
