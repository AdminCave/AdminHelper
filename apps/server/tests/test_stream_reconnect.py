# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SSE Redis reader reconnect (4.72): a lost Redis connection must not permanently kill the
per-worker reader — it must reconnect and keep delivering refresh nudges. Uses a fake pubsub, so
it needs no real Redis (unlike the round-trip integration test)."""

import asyncio
import contextlib
import json
import logging

from app.modules.notifications import stream_hub


def test_reader_reconnects_after_connection_error(monkeypatch):
    # The old except sat OUTSIDE the while loop, so one ConnectionError from get_message ended the
    # reader for good. Now it must reconnect and deliver a message that arrives after the outage.
    monkeypatch.setattr(stream_hub, "_RECONNECT_DELAY", 0.0)  # skip the real backoff sleep
    delivered: list[tuple[int, str]] = []
    monkeypatch.setattr(stream_hub, "deliver_local", lambda uid, p: delivered.append((uid, p)))

    calls = {"n": 0}
    subscribed = {"n": 0}

    class _FakePubSub:
        async def get_message(self, **_kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("redis restart")
            if calls["n"] == 2:
                return {"data": json.dumps({"maxId": 7, "user_ids": [42]})}
            raise asyncio.CancelledError

        async def subscribe(self, _ch):
            subscribed["n"] += 1

    async def scenario():
        with contextlib.suppress(asyncio.CancelledError):
            await stream_hub._reader(_FakePubSub())

    asyncio.run(scenario())

    assert subscribed["n"] == 1  # reconnected once after the ConnectionError
    assert delivered == [
        (42, json.dumps({"type": "refresh", "maxId": 7}))
    ]  # delivered post-reconnect


class _FakeRedis:
    def __init__(self, pubsub):
        self._pubsub = pubsub

    def pubsub(self):
        return self._pubsub


def _start_with(monkeypatch, pubsub) -> None:
    """stream_hub.start() against a fake Redis, then the reader it started is cancelled."""
    import redis.asyncio as aioredis

    monkeypatch.setattr(aioredis, "from_url", lambda *_a, **_kw: _FakeRedis(pubsub))
    monkeypatch.setattr(stream_hub, "_redis", None)
    monkeypatch.setattr(stream_hub, "_reader_task", None)

    async def scenario():
        await stream_hub.start("redis://fake")
        task = stream_hub._reader_task
        assert task is not None  # the reader runs in both cases
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_start_reads_the_subscribe_confirmation_before_the_reader_starts(monkeypatch):
    # R-0149: subscribe() only sends SUBSCRIBE. A publish before Redis confirms it is lost,
    # so start() reads the confirmation itself — before the reader task exists.
    seen = []

    class _ConfirmingPubSub:
        subscribed = False

        async def subscribe(self, _ch):
            self.subscribed = True

        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            if not ignore_subscribe_messages and self.subscribed:
                seen.append(stream_hub._reader_task is None)
                return {"type": "subscribe", "channel": b"notif:events", "data": 1}
            await asyncio.sleep(0.01)
            return None

    _start_with(monkeypatch, _ConfirmingPubSub())
    assert seen == [True]


def test_start_without_confirmation_warns_and_starts_the_reader(monkeypatch, caplog):
    monkeypatch.setattr(stream_hub, "_SUBSCRIBE_TIMEOUT", 0.2)

    class _SilentPubSub:
        async def subscribe(self, _ch):
            pass

        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            await asyncio.sleep(min(timeout or 0.05, 0.05))
            return None

    with caplog.at_level(logging.WARNING, logger=stream_hub.logger.name):
        _start_with(monkeypatch, _SilentPubSub())
    assert any("did not confirm the subscription" in r.getMessage() for r in caplog.records)
