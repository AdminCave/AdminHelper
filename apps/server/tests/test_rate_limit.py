# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""InMemoryBackend thread-safety (4.66): sync endpoints (login/bootstrap/hook-trigger) run in
the FastAPI threadpool, so the backend is hit from many threads at once."""

import threading

from app.core.rate_limit import InMemoryBackend


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
