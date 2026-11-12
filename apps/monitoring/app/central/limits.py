# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Restraint toward the targets of central checks (R-1224, concept §3.13 item 5).

At most MAX_PARALLEL central runs at a time, at least ADDRESS_SPACING_S between two
connections to one address, and at least MAIL_SPACING_S between two SMTP/IMAP
connections to one address and port, over all checks. A run that cannot keep to
this is skipped and the check keeps its state: a missing data point is better than
a target that blocks us (postscreen) or slows down.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

MAX_PARALLEL = 4
# Waits are short and bounded: a waiting run holds one of the scheduler's shared
# pool threads, which the other checks need.
SLOT_WAIT_S = 10.0
ADDRESS_SPACING_S = 2.0
SPACING_WAIT_S = 10.0
MAIL_SPACING_S = 15 * 60.0
# An interval job fires a little early or late (pool wait, DNS); without the slack a
# check whose interval equals the spacing would be skipped every other run.
MAIL_SPACING_SLACK_S = 30.0

SKIPPED_SPACING_MESSAGE = "skipped: minimum spacing"
SKIPPED_BUSY_MESSAGE = "skipped: too many central checks at once"


class RunSkipped(Exception):
    """A central run left out to keep to the limits; the check keeps its state.

    The message (one of the SKIPPED_* above) is noted in the check's message.
    """


class Limits:
    """The per-process bookkeeping; `clock` and `sleep` are injectable for tests."""

    def __init__(
        self,
        *,
        max_parallel: int = MAX_PARALLEL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._slots = threading.BoundedSemaphore(max_parallel)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_start: dict[str, float] = {}
        self._last_mail: dict[tuple[str, int], float] = {}

    @contextmanager
    def slot(self, timeout: float = SLOT_WAIT_S) -> Iterator[bool]:
        """Holds one of the parallel slots; yields False when none freed up within `timeout`."""
        acquired = self._slots.acquire(timeout=timeout)
        try:
            yield acquired
        finally:
            if acquired:
                self._slots.release()

    def address_turn(self, address: str) -> bool:
        """Waits until `address` may be contacted; False (no wait) when that is over SPACING_WAIT_S away.

        The next start is reserved before the wait, so runs queued on one address
        go one after the other instead of all at once when the wait ends.
        """
        with self._lock:
            now = self._clock()
            self._prune(now)
            start = max(now, self._next_start.get(address, now))
            if start - now > SPACING_WAIT_S:
                return False
            self._next_start[address] = start + ADDRESS_SPACING_S
        if start > now:
            self._sleep(start - now)
        return True

    def mail_turn(self, address: str, port: int) -> bool:
        """True and recorded when no SMTP/IMAP connection to `address`:`port` is in the last MAIL_SPACING_S."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            last = self._last_mail.get((address, port))
            if last is not None and now - last < MAIL_SPACING_S - MAIL_SPACING_SLACK_S:
                return False
            self._last_mail[(address, port)] = now
            return True

    def _prune(self, now: float) -> None:
        # Entries that no longer hold anything back go, so the tables stay as small
        # as the set of targets contacted lately.
        for address in [a for a, start in self._next_start.items() if start <= now]:
            del self._next_start[address]
        for key in [k for k, last in self._last_mail.items() if now - last >= MAIL_SPACING_S]:
            del self._last_mail[key]


LIMITS = Limits()
