# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Integration test for the SSE Redis fan-out — the cross-worker mechanism the
unit tests can't cover. Exercises the real round-trip: a sync publish() (the
ingest path) reaches the async reader over Redis Pub/Sub and lands in a locally
registered stream's queue. Skipped when no Redis is reachable (e.g. PR CI)."""

import asyncio
import json
import os

import pytest

from app.modules.notifications import stream_hub

# The default is the PR CI's service container (ci.yml); the integration layer
# points it at the compose stack's Redis (scripts/tests/stack_pytest.sh).
REDIS_URL = os.environ.get("AH_TEST_REDIS_URL", "redis://localhost:6380/0")


def _redis_available() -> bool:
    try:
        import redis

        redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_available(), reason=f"Redis not reachable at {REDIS_URL}"
)


def test_redis_fanout_roundtrip(monkeypatch):
    # publish() reads REDIS_URL from config at call time.
    monkeypatch.setattr("app.core.config.REDIS_URL", REDIS_URL)

    async def scenario():
        await stream_hub.start(REDIS_URL)
        q = stream_hub.register(42)
        try:
            stream_hub.publish([42], 7)  # sync, as called from ingest_event
            payload = await asyncio.wait_for(q.get(), timeout=3)
        finally:
            stream_hub.unregister(42, q)
            await stream_hub.stop()
        return payload

    data = json.loads(asyncio.run(scenario()))
    assert data["type"] == "refresh"
    assert data["maxId"] == 7


def test_redis_fanout_only_to_targeted_user(monkeypatch):
    monkeypatch.setattr("app.core.config.REDIS_URL", REDIS_URL)

    async def scenario():
        await stream_hub.start(REDIS_URL)
        target = stream_hub.register(1)
        other = stream_hub.register(2)
        try:
            stream_hub.publish([1], 5)
            await asyncio.wait_for(target.get(), timeout=3)
            # The non-targeted user's queue must stay empty.
            return other.empty()
        finally:
            stream_hub.unregister(1, target)
            stream_hub.unregister(2, other)
            await stream_hub.stop()

    assert asyncio.run(scenario()) is True
