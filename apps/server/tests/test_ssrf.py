# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DNS resolution of the server's SSRF guard (harness 8a T5, R-0042).

The address classification itself is covered by the monitoring suite
(apps/monitoring/tests/test_ssrf.py) and pinned to this copy by
test_ssrf_parity.py — repeating the range table here would be the second copy
this stage exists to prevent. What is specific to this file is the mechanism
around it: a hung resolver must neither park the caller for the OS default nor,
since R-0042, park *every other* caller with it.
"""

import ipaddress
import logging
import socket
import threading
import time
import types

import pytest

import app.core.ssrf as ssrf_mod

# One public A record, so a stubbed resolution that succeeds is distinguishable
# from a fail-closed one: the guard answers False only on a real, public result.
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


def test_dns_resolution_times_out_and_fails_closed(monkeypatch):
    # The hook worker reaches this guard from the unauthenticated public webhook,
    # so the target host is attacker-chosen: pointed at a dead nameserver, an
    # uncapped getaddrinfo parks the worker for ~30 s per request (4.111).
    release = threading.Event()
    entered = threading.Semaphore(0)
    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", _hanging_resolver(release, entered))
    monkeypatch.setattr(ssrf_mod, "_DNS_TIMEOUT_S", 0.1)

    try:
        start = time.monotonic()
        assert ssrf_mod.is_private_url("http://hang-forever.example") is True
        # Fail-closed is only half the guarantee; returning promptly is the other.
        assert time.monotonic() - start < 1.0
    finally:
        # Released here rather than slept out, so no resolver thread outlives the test
        # holding a permit while a later test rebinds the semaphore.
        release.set()


def test_hung_resolutions_do_not_block_a_healthy_one(monkeypatch):
    # R-0042: with the shared four-worker pool this replaced, four hung lookups held every
    # worker, so the fifth caller fell into its own 5 s deadline and fail-closed reported
    # "private" — the guard refusing a healthy target. Service-wide that is the monitoring
    # copy this file mirrors (one pool behind every check); here it is one hook worker
    # resolving several hosts. Either way four hung resolutions must cost the fifth nothing.
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
    # One thread per call needs an upper bound, or the attacker trades the starved pool
    # for unbounded thread creation. Over the cap the guard fails closed immediately —
    # without waiting out the deadline it could not start anyway.
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
    # A non-daemon thread is joined at interpreter exit, so a resolution still stuck in
    # the kernel would hold up SIGTERM shutdown of the whole service.
    seen: dict[str, bool] = {}

    def _stub(*_a, **_k):
        seen["daemon"] = threading.current_thread().daemon
        return _PUBLIC_ADDRINFO

    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", _stub)

    assert ssrf_mod.is_private_url("http://healthy.example") is False
    assert seen["daemon"] is True


def test_a_failed_thread_start_hands_the_permit_back(monkeypatch):
    # The permit is taken before the thread exists, so a Thread.start() that raises (thread
    # exhaustion, interpreter shutdown) would lose it for good: 64 such failures and the guard
    # answers "private" to every target until the service restarts — worse than the starvation
    # it replaces, because it does not heal. script_runner.py guards its hook semaphore the
    # same way.
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


def test_a_resolution_error_hands_the_permit_back(monkeypatch):
    # NXDOMAIN and SERVFAIL are the everyday case, not the exception. If the permit came back
    # only on the success path, 64 bad hostnames would close the guard for good — and every
    # other test here would still pass, because none of them makes the resolver raise.
    monkeypatch.setattr(ssrf_mod, "_DNS_INFLIGHT", threading.BoundedSemaphore(2))

    def _failing(*_a, **_k):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", _failing)

    for _ in range(3):  # one more than there are permits: a leak would strand the guard here
        assert ssrf_mod.is_private_url("http://nxdomain.example") is True

    assert ssrf_mod._DNS_INFLIGHT.acquire(blocking=False) is True
    assert ssrf_mod._DNS_INFLIGHT.acquire(blocking=False) is True


def test_a_thread_constructor_failure_hands_the_permit_back(monkeypatch):
    # The permit is taken before the thread object even exists. A constructor that raises
    # something other than RuntimeError must not swallow it — but it must not keep the permit
    # either: 64 of those and the guard is closed for good.
    class _Unconstructable:
        def __init__(self, *_a, **_k):
            raise MemoryError("out of memory")

    monkeypatch.setattr(ssrf_mod, "_DNS_INFLIGHT", threading.BoundedSemaphore(2))
    monkeypatch.setattr(ssrf_mod, "threading", types.SimpleNamespace(Thread=_Unconstructable))

    for _ in range(3):  # one more than there are permits: a leak would strand the guard here
        with pytest.raises(MemoryError):
            ssrf_mod.is_private_url("http://healthy.example")

    assert ssrf_mod._DNS_INFLIGHT.acquire(blocking=False) is True
    assert ssrf_mod._DNS_INFLIGHT.acquire(blocking=False) is True


# R-0045: both rejections fail closed, but a target that does not resolve is not one
# that resolves privately — the callers tell the operator which of the two it is.
@pytest.mark.parametrize(
    ("url", "verdict"),
    [
        ("http://127.0.0.1/", "PRIVATE"),
        ("http://93.184.216.34/", "ALLOWED"),
        ("http://", "UNRESOLVED"),  # no host
    ],
)
def test_classify_url_names_the_reason(url, verdict):
    assert ssrf_mod.classify_url(url) is ssrf_mod.UrlVerdict[verdict]


def test_a_host_that_does_not_resolve_is_unresolved_not_private(monkeypatch):
    # DNS error, missed deadline and the in-flight cap all reach the caller as None.
    monkeypatch.setattr(ssrf_mod, "_resolve", lambda _host, _timeout: None)
    assert (
        ssrf_mod.classify_url("http://dead-nameserver.example/") is ssrf_mod.UrlVerdict.UNRESOLVED
    )


def test_an_empty_address_list_is_unresolved_not_private(monkeypatch):
    # Through the real _resolve: a lookup that succeeds with no address has nothing to
    # classify, so the verdict is the one for "does not resolve", not a blocked address.
    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", lambda *_a, **_k: [])
    assert ssrf_mod.classify_url("http://no-addresses.example/") is ssrf_mod.UrlVerdict.UNRESOLVED


def test_an_unreadable_address_is_private_not_unresolved(monkeypatch):
    # The host did resolve, just to something ipaddress cannot read — fail-closed counts
    # that as a blocked address, not as a lookup that never answered.
    unreadable = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-address", 0))]
    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", lambda *_a, **_k: unreadable)
    assert ssrf_mod.classify_url("http://garbled.example/") is ssrf_mod.UrlVerdict.PRIVATE


def test_is_private_url_still_rejects_for_both_reasons(monkeypatch):
    assert ssrf_mod.is_private_url("http://127.0.0.1/") is True
    assert ssrf_mod.is_private_url("http://") is True
    monkeypatch.setattr(ssrf_mod, "_resolve", lambda _host, _timeout: None)
    assert ssrf_mod.is_private_url("http://dead-nameserver.example/") is True


@pytest.mark.parametrize(
    "url", ["http://[::1", "http://[", "http://[fe80::1%25eth0", "https://[::1:8443/x"]
)
def test_a_malformed_ipv6_literal_is_rejected_not_raised(url):
    # urlparse raises ValueError on these (R-0181); the guard answers with a verdict.
    assert ssrf_mod.classify_url(url) is ssrf_mod.UrlVerdict.PRIVATE
    assert ssrf_mod.is_private_url(url) is True


def _resolving_to(monkeypatch, address: str) -> None:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    answer = [(family, socket.SOCK_STREAM, 6, "", (address, 0))]
    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", lambda *_a, **_k: answer)


# R-1080: allow_networks opens the private networks the operator named for targets chosen
# on purpose, and nothing else. Documentation addresses stand in for public ones where the
# range matters; the real public answer is the one from _PUBLIC_ADDRINFO.
_NET = ipaddress.ip_network
_EVERY_PRIVATE = tuple(
    _NET(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
)
# Every address there is, so the hard block shows it does not depend on what the list holds.
_EVERYTHING = (_NET("0.0.0.0/0"), _NET("::/0"))


@pytest.mark.parametrize(
    ("address", "network"),
    [
        ("10.1.2.3", "10.1.0.0/16"),
        ("172.16.0.1", "172.16.0.0/12"),
        ("192.168.1.10", "192.168.1.0/24"),
        ("100.64.0.1", "100.64.0.0/10"),  # CGNAT
        ("100.127.255.254", "100.64.0.0/10"),
        ("fc00::1", "fc00::/7"),
        ("fd12:3456::1", "fd12:3456::/32"),
        ("fec0::1", "fec0::/10"),  # deprecated site-local, global to ipaddress
        ("feff:ffff::1", "fec0::/10"),
        ("::ffff:192.168.1.10", "192.168.1.0/24"),  # IPv4-mapped, matched as IPv4
    ],
)
def test_a_private_address_passes_only_inside_a_listed_network(monkeypatch, address, network):
    _resolving_to(monkeypatch, address)
    url = "http://lan-target.example/"
    assert ssrf_mod.check_target(url).verdict is ssrf_mod.UrlVerdict.PRIVATE
    allowed = ssrf_mod.check_target(url, allow_networks=(_NET(network),))
    assert allowed.verdict is ssrf_mod.UrlVerdict.ALLOWED
    assert allowed.addresses == (address.removeprefix("::ffff:"),)


@pytest.mark.parametrize(
    ("address", "networks"),
    [
        ("192.168.2.10", ("192.168.1.0/24",)),  # the neighbouring network
        ("172.18.0.5", ("192.168.0.0/16", "10.0.0.0/8")),
        ("10.0.0.1", ("100.64.0.0/10",)),
        ("100.64.0.1", ("10.0.0.0/8",)),
        ("fd12:3456::1", ("fd99::/16",)),
        ("fec0::1", ("fc00::/7",)),
        ("::ffff:10.0.0.1", ("::ffff:0:0/96",)),  # the mapped form is matched as IPv4
    ],
)
def test_a_private_address_outside_the_listed_networks_stays_blocked(
    monkeypatch, address, networks
):
    _resolving_to(monkeypatch, address)
    target = ssrf_mod.check_target(
        "http://lan-target.example/", allow_networks=tuple(_NET(n) for n in networks)
    )
    assert target.verdict is ssrf_mod.UrlVerdict.PRIVATE
    assert target.addresses == ()


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.8.9.10",
        "::1",
        "169.254.169.254",  # cloud metadata
        "169.254.0.1",
        "fe80::1",
        "fd00:ec2::254",  # cloud metadata over IPv6
        "fd00:ec2::23",
        "fd20:ce::254",
        "100.100.100.200",  # cloud metadata inside CGNAT
        "168.63.129.16",  # cloud metadata on a public address
        "::ffff:168.63.129.16",
        "2002:a83f:8110::1",  # 6to4 around 168.63.129.16
        "0.0.0.0",
        "0.1.2.3",
        "::",
        "224.0.0.1",
        "ff02::1",
        "240.0.0.1",
        "255.255.255.255",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "::7f00:1",  # IPv4-compatible 127.0.0.1
        "64:ff9b::7f00:1",  # NAT64 around 127.0.0.1
        "64:ff9b::a9fe:a9fe",  # NAT64 around 169.254.169.254
        "2002:a9fe:a9fe::1",  # 6to4 around 169.254.169.254
        "2002:7f00:1::1",  # 6to4 around 127.0.0.1
        "2001:0:4136:e378:8000:63bf:80ff:fffe",  # Teredo around 127.0.0.1
    ],
)
def test_an_always_blocked_address_stays_blocked_whatever_the_list_holds(monkeypatch, address):
    _resolving_to(monkeypatch, address)
    url = "http://lan-target.example/"
    for networks in ((), _EVERY_PRIVATE, _EVERYTHING):
        target = ssrf_mod.check_target(url, allow_networks=networks)
        assert target.verdict is ssrf_mod.UrlVerdict.PRIVATE, networks
        assert target.addresses == ()


def test_a_public_address_passes_whatever_the_list_holds(monkeypatch):
    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", lambda *_a, **_k: _PUBLIC_ADDRINFO)
    for networks in ((), _EVERY_PRIVATE):
        target = ssrf_mod.check_target("http://public.example/", allow_networks=networks)
        assert target.verdict is ssrf_mod.UrlVerdict.ALLOWED
        assert target.addresses == ("93.184.216.34",)


def test_one_blocked_address_among_listed_ones_rejects_the_host(monkeypatch):
    answer = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
    ]
    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", lambda *_a, **_k: answer)
    target = ssrf_mod.check_target("http://split.example/", allow_networks=_EVERYTHING)
    assert target.verdict is ssrf_mod.UrlVerdict.PRIVATE


def test_one_unlisted_private_address_rejects_the_host(monkeypatch):
    answer = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.18.0.5", 0)),
    ]
    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", lambda *_a, **_k: answer)
    target = ssrf_mod.check_target(
        "http://split.example/", allow_networks=(_NET("192.168.1.0/24"),)
    )
    assert target.verdict is ssrf_mod.UrlVerdict.PRIVATE
