# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SSE Redis reader reconnect (4.72): a lost Redis connection must not permanently kill the
per-worker reader — it must reconnect and keep delivering refresh nudges. Uses a fake pubsub, so
it needs no real Redis (unlike the round-trip integration test)."""

import asyncio
import contextlib
import json

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
