# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SSRF guard (3.26): the shared is_private_url must block every internal-target
class — including the ones the original range list missed (0.0.0.0, IPv4-mapped
IPv6) — and fail closed on an unresolvable host. Since R-0042 it also covers the
resolution mechanism itself: a hung lookup must not park the next caller, and the
in-flight cap must fail closed without leaking its permit."""

import logging
import socket
import threading
import time
import types

import pytest

import app.core.ssrf as ssrf_mod
from app.core.ssrf import is_private_url

# One public A record, so a stubbed resolution that succeeds is distinguishable from a
# fail-closed one: the guard answers False only on a real, public result.
_PUBLIC_ADDRINFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def _hanging_resolver(release: threading.Event, entered: threading.Semaphore):
    """A getaddrinfo stub that blocks until `release`, and signals each entry on `entered`."""

    def _stub(host, *_a, **_k):
        if not host.startswith("hang"):
            return _PUBLIC_ADDRINFO
        entered.release()
        release.wait(10)  # bounded, so a failing test cannot leave the thread behind forever
        return _PUBLIC_ADDRINFO

    return _stub


@pytest.mark.parametrize(
    "url",
    [
        "http://0.0.0.0:8428",  # unspecified -> localhost on Linux (was allowed)
        "http://0.1.2.3",  # rest of 0.0.0.0/8
        "http://127.0.0.1",
        "http://10.0.0.5",
        "http://172.16.0.1",  # RFC1918 172.16/12
        "http://192.168.1.1",
        "http://169.254.169.254",  # cloud metadata (link-local)
        "http://100.64.0.1",  # CGNAT
        "http://[::1]",
        "http://[::ffff:127.0.0.1]",  # IPv4-mapped IPv6 (was allowed)
        "http://[fc00::1]",  # unique-local IPv6
        "http://[fe80::1]",  # link-local IPv6
        "http://nonexistent.invalid.example",  # unresolvable -> fail closed (was allowed)
        "",  # no hostname
        "not-a-url",
    ],
)
def test_blocks_private_reserved_and_unresolvable(url):
    assert is_private_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://93.184.216.34",  # public IPv4 literal
        "http://[2606:2800:220:1:248:1893:25c8:1946]",  # public IPv6 literal
    ],
)
def test_allows_public_targets(url):
    assert is_private_url(url) is False


def test_dns_resolution_times_out_and_fails_closed(monkeypatch):
    # 4.111: a hung/slow DNS resolution must not block indefinitely — is_private_url caps it with a
    # hard deadline and fails closed (treats the target as private) instead of stalling the worker.
    def _slow_getaddrinfo(*_a, **_k):
        time.sleep(2)  # simulate a hung resolver
        return []

    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", _slow_getaddrinfo)
    monkeypatch.setattr(ssrf_mod, "_DNS_TIMEOUT_S", 0.1)  # short deadline for the test

    start = time.monotonic()
    assert ssrf_mod.is_private_url("http://slow-dns.example") is True
    # Fail-closed is only half the guarantee; returning promptly is the other.
    assert time.monotonic() - start < 1.0


def test_hung_resolutions_do_not_block_a_healthy_one(monkeypatch):
    # R-0042, the reason this service is the worst hit: the guard used to resolve through one
    # four-worker pool shared by every check (scheduler pool 30) and every alert webhook
    # (_alert_pool 5). Four hung lookups held all four workers, so every other check fell into
    # its own 5 s deadline and fail-closed reported "private" — one dead nameserver and the
    # whole service stops reaching any target. Hung resolutions must now cost the next one
    # nothing.
    release = threading.Event()
    entered = threading.Semaphore(0)
    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", _hanging_resolver(release, entered))
    monkeypatch.setattr(ssrf_mod, "_DNS_TIMEOUT_S", 5)

    hung = [
        threading.Thread(
            target=ssrf_mod.is_private_url, args=(f"http://hang{i}.example",), daemon=True
        )
        for i in range(4)
    ]
    try:
        for thread in hung:
            thread.start()
        for _ in hung:  # all four are really inside getaddrinfo, not merely started
            assert entered.acquire(timeout=5)

        start = time.monotonic()
        assert ssrf_mod.is_private_url("http://healthy.example") is False
        assert time.monotonic() - start < 0.5
    finally:
        release.set()
        for thread in hung:
            thread.join(5)


def test_in_flight_cap_rejects_at_once_and_warns_at_most_once_per_interval(monkeypatch, caplog):
    # One thread per call needs an upper bound, or the attacker trades the starved pool for
    # unbounded thread creation. Over the cap the guard fails closed immediately — the
    # resolution it would have waited for cannot even start.
    release = threading.Event()
    entered = threading.Semaphore(0)
    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", _hanging_resolver(release, entered))
    monkeypatch.setattr(ssrf_mod, "_DNS_TIMEOUT_S", 5)
    monkeypatch.setattr(ssrf_mod, "_DNS_MAX_INFLIGHT", 2)
    monkeypatch.setattr(ssrf_mod, "_DNS_INFLIGHT", threading.BoundedSemaphore(2))
    monkeypatch.setattr(ssrf_mod, "_dns_cap_warned_at", None)

    hung = [
        threading.Thread(
            target=ssrf_mod.is_private_url, args=(f"http://hang{i}.example",), daemon=True
        )
        for i in range(2)
    ]
    try:
        for thread in hung:
            thread.start()
        for _ in hung:
            assert entered.acquire(timeout=5)

        with caplog.at_level(logging.WARNING, logger=ssrf_mod.__name__):
            start = time.monotonic()
            assert ssrf_mod.is_private_url("http://over-cap.example") is True
            assert time.monotonic() - start < 0.5
            assert ssrf_mod.is_private_url("http://over-cap-again.example") is True

        capped = [r for r in caplog.records if "in flight" in r.getMessage()]
        assert len(capped) == 1, f"one warning per interval, not per rejected call: {capped}"
    finally:
        release.set()
        for thread in hung:
            thread.join(5)
        # Both permits have to be back before monkeypatch restores the real semaphore —
        # a release arriving later would land on the 64-permit one and raise. Reclaiming
        # them here is also the in-flight balance check for the hung path.
        for _ in hung:
            assert ssrf_mod._DNS_INFLIGHT.acquire(timeout=5)


def test_resolution_runs_in_a_daemon_thread(monkeypatch):
    # A non-daemon thread is joined at interpreter exit, so a resolution still stuck in the
    # kernel would hold up SIGTERM shutdown of the monitoring service.
    seen: dict[str, bool] = {}

    def _stub(*_a, **_k):
        seen["daemon"] = threading.current_thread().daemon
        return _PUBLIC_ADDRINFO

    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", _stub)

    assert ssrf_mod.is_private_url("http://healthy.example") is False
    assert seen["daemon"] is True


def test_a_failed_thread_start_hands_the_permit_back(monkeypatch):
    # The permit is taken before the thread exists, so a Thread.start() that raises (thread
    # exhaustion, interpreter shutdown) would lose it for good: 64 such failures and every
    # check target counts as private until the service restarts — a state that, unlike the
    # starvation it replaces, does not heal.
    class _UnstartableThread:
        def __init__(self, *_a, **_k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(ssrf_mod, "_DNS_INFLIGHT", threading.BoundedSemaphore(2))
    monkeypatch.setattr(ssrf_mod, "threading", types.SimpleNamespace(Thread=_UnstartableThread))

    for _ in range(3):  # one more than there are permits: a leak would strand the guard here
        assert ssrf_mod.is_private_url("http://healthy.example") is True

    assert ssrf_mod._DNS_INFLIGHT.acquire(blocking=False) is True
    assert ssrf_mod._DNS_INFLIGHT.acquire(blocking=False) is True


def test_an_empty_address_list_fails_closed(monkeypatch):
    # A resolution that yields no address at all is as unresolved as one that raised —
    # "no address" must never read as "not private".
    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", lambda *_a, **_k: [])

    assert ssrf_mod.is_private_url("http://no-addresses.example") is True
