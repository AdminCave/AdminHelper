# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Property tests for the SSRF guard: every address, not the dozen we thought of.

is_private_url decides whether an outbound target from a hook script may be
reached. The existing suites pin the addresses a human wrote down; this one
generates them and checks the verdict against an oracle built from the
`ipaddress` module itself — a different route to the same answer, so a category
the guard forgot shows up as a disagreement rather than as a gap nobody notices.

The resolver is replaced throughout: what is under test is the decision, not DNS,
and a test that resolved for real would be slow, flaky and would reach the network
from a unit suite. The replacement uses a context manager rather than the
monkeypatch fixture — a function-scoped fixture is set up once per test, not once
per generated example, which is exactly what Hypothesis' health check objects to.
"""

from __future__ import annotations

import ipaddress
import socket
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st

from app.core import ssrf
from app.core.ssrf import _BLOCKED_NETWORKS, is_private_url


def _addr_info(address: str) -> list:
    """What socket.getaddrinfo returns, reduced to the shape _resolve produces."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, 0))]


def _resolving_to(*addresses: str):
    """Replaces the resolver with one that answers with exactly these addresses."""
    answer = [entry for address in addresses for entry in _addr_info(address)]
    return patch.object(ssrf, "_resolve", lambda host, timeout: answer)


def _oracle_is_private(ip) -> bool:
    """The verdict derived from ipaddress' own categories.

    Deliberately a second implementation rather than a call into the guard: two
    routes to the same answer is the whole point of a differential test.
    """
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or any(ip in net for net in _BLOCKED_NETWORKS)
    )


@given(ip=st.ip_addresses())
@example(ip=ipaddress.ip_address("127.0.0.1"))
@example(ip=ipaddress.ip_address("169.254.169.254"))  # cloud metadata
@example(ip=ipaddress.ip_address("10.0.0.1"))
@example(ip=ipaddress.ip_address("100.64.0.1"))  # CGNAT, only via _BLOCKED_NETWORKS
@example(ip=ipaddress.ip_address("0.0.0.0"))  # "this network" -> localhost on Linux
@example(ip=ipaddress.ip_address("8.8.8.8"))  # public, must be allowed
@example(ip=ipaddress.ip_address("::1"))
@example(ip=ipaddress.ip_address("2001:4860:4860::8888"))
@settings(max_examples=300, deadline=None)
def test_verdict_matches_the_ipaddress_categories(ip):
    with _resolving_to(str(ip)):
        assert is_private_url("http://target.example/") is _oracle_is_private(ip)


@given(ip=st.ip_addresses(v=4))
@example(ip=ipaddress.ip_address("127.0.0.1"))
@example(ip=ipaddress.ip_address("8.8.8.8"))
@settings(max_examples=200, deadline=None)
def test_ipv4_mapped_ipv6_is_judged_as_the_embedded_ipv4(ip):
    """::ffff:127.0.0.1 must be as private as 127.0.0.1 — the mapping is the
    classic way past a guard that only looks at IPv4 categories."""
    with _resolving_to(f"::ffff:{ip}"):
        mapped_verdict = is_private_url("http://target.example/")
    with _resolving_to(str(ip)):
        plain_verdict = is_private_url("http://target.example/")

    assert mapped_verdict == plain_verdict


# The shapes where two URL parsers are known to disagree: userinfo before the host,
# a second @, bracketed IPv6, a backslash where a slash is expected, percent-encoding,
# an empty port. A plain hostname would never separate them.
CONFUSING_URL = st.one_of(
    st.builds(
        lambda scheme, userinfo, host, port, path: f"{scheme}://{userinfo}{host}{port}{path}",
        scheme=st.sampled_from(["http", "https"]),
        userinfo=st.sampled_from(["", "user@", "user:pw@", "a@b@", "@", "user%40evil@"]),
        host=st.sampled_from(
            ["example.test", "127.0.0.1", "[::1]", "[::ffff:127.0.0.1]", "localhost", "0x7f.1"]
        ),
        port=st.sampled_from(["", ":80", ":", ":0"]),
        path=st.sampled_from(["", "/", "/a", "\\evil.test", "/?x=1", "/#f", "/..%2f"]),
    ),
)


@given(url=CONFUSING_URL)
@example(url="http://example.test/")
@example(url="http://user@example.test/")
@example(url="http://a@b@example.test/")
@example(url="http://[::1]/")
@example(url="http://example.test\\evil.test/")
@settings(max_examples=300, deadline=None)
def test_the_guard_checks_the_host_that_httpx_will_actually_fetch(url):
    """Differential against the parser the REQUEST uses, not the one next door.

    is_private_url parses with urlparse; the fetch that follows it runs through
    httpx (script_worker.py::_safe_http_get -> httpx.stream). If those two read a
    different host out of the same string, the guard clears one address and the
    client connects to another — the parser-confusion shape of an SSRF bypass, and
    the reason comparing urlparse against urlsplit proves nothing (urlparse calls
    urlsplit internally, so they cannot disagree by construction).
    """
    try:
        fetched_host = httpx.URL(url).host
    except httpx.InvalidURL:
        return  # httpx refuses to fetch it at all, so there is nothing to bypass

    seen: list[str] = []

    def _record(hostname, timeout):
        seen.append(hostname)
        return _addr_info("8.8.8.8")

    with patch.object(ssrf, "_resolve", _record):
        verdict = is_private_url(url)

    if not seen:
        # The guard never resolved: it failed closed on a URL it could not read.
        assert verdict is True
        return

    # httpx lowercases and IDNA-encodes; compare on that footing, and strip the
    # brackets urlparse leaves off an IPv6 literal.
    guard_host = seen[0].lower().strip("[]")
    assert guard_host == fetched_host.lower().strip("[]"), (
        f"guard checked {seen[0]!r}, httpx would fetch {fetched_host!r} — from {url!r}"
    )


@given(
    url=st.sampled_from(["", "http://", "not a url", "///path", "http:///x", "file:///etc/passwd"])
)
@settings(max_examples=10, deadline=None)
def test_unparseable_targets_fail_closed(url):
    """No host, no verdict — and "no verdict" has to mean "private"."""
    assume(not urlsplit(url).hostname)  # a parseable host is the test above

    with _resolving_to("8.8.8.8"):
        assert is_private_url(url) is True


@given(bad=st.sampled_from(["", "not-an-ip", "999.999.999.999", "::fffff", " 8.8.8.8"]))
@settings(max_examples=10, deadline=None)
def test_an_unparseable_resolver_answer_fails_closed(bad):
    """A resolver that answers with something ipaddress cannot read must not be
    treated as "not private" — the guard catches the ValueError and says private."""
    with _resolving_to(bad):
        assert is_private_url("http://target.example/") is True


def test_a_resolver_that_gives_up_fails_closed():
    """Timeout, in-flight cap, empty answer — _resolve returns None for all three."""
    with patch.object(ssrf, "_resolve", lambda host, timeout: None):
        assert is_private_url("http://target.example/") is True


# Drawn from fixed networks rather than filtered out of the whole space: almost
# every random v4 address is public, so `assume(is_private(...))` threw away most
# of what it generated and Hypothesis rightly complained.
@given(
    public=st.ip_addresses(v=4, network="8.8.0.0/16"),
    private=st.one_of(
        st.ip_addresses(v=4, network="10.0.0.0/8"),
        st.ip_addresses(v=4, network="127.0.0.0/8"),
        st.ip_addresses(v=4, network="169.254.0.0/16"),
        st.ip_addresses(v=4, network="100.64.0.0/10"),
    ),
)
@settings(max_examples=100, deadline=None)
def test_one_private_address_among_many_is_enough(public, private):
    """A host with several A records is private if ANY of them is — checking only
    the first answer is how a round-robin record slips an internal target past."""
    assert not _oracle_is_private(public) and _oracle_is_private(private)

    with _resolving_to(str(public), str(private)):
        assert is_private_url("http://target.example/") is True
