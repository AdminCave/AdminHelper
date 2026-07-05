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
