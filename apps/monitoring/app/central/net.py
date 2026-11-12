# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which address a central check counts as global, and so may connect to (R-1224).

ipaddress.is_global follows the IANA special-purpose address registries, but each
Python release carries its own copy of them: 3.13 and 3.14 both still count
192.88.99.0/24, 100:0:0:1::/64 and 5f00::/16 as global and 2001:1::3 as not. The
rows pinned here (registries as fetched on 2026-11-12) decide first, so the answer
is the same on every Python. IPv6 outside 2000::/3, the only block IANA allocates
global unicast from, is never global: ipaddress counts parts of it as global
(IPv4-compatible ::/96, 4000::/3). ipaddress only decides what neither covers, where
a newer Python can make the answer stricter but never wider.

An IPv6-only environment may run NAT64 with a prefix of its own (RFC 6052) instead
of 64:ff9b::/96. The prefixes are learned from the system resolver (RFC 7050). An
address under one of them is global only if its embedded IPv4 address is global as
well: a learned prefix can make the answer stricter, never wider, so a forged answer
costs at most a target judged not public.
"""

from __future__ import annotations

import ipaddress
import threading
import time

import dns.exception
import dns.name
import dns.resolver

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")
_GLOBAL_UNICAST = ipaddress.IPv6Network("2000::/3")

# "Globally Reachable: True" rows that lie inside a wider non-global block below
# (192.0.0.0/24, 2001::/23) or that ipaddress gets wrong. They are checked first.
_GLOBAL = tuple(
    ipaddress.ip_network(n)
    for n in (
        "192.0.0.9/32",
        "192.0.0.10/32",
        "192.31.196.0/24",
        "192.52.193.0/24",
        "192.175.48.0/24",
        "2001:1::1/128",
        "2001:1::2/128",
        "2001:1::3/128",
        "2001:3::/32",
        "2001:4:112::/48",
        "2001:20::/28",
        "2001:30::/28",
        "2620:4f:8000::/48",
    )
)

# "Globally Reachable: False" rows, the deprecated ones without a value
# (192.88.99.0/24, 2001:10::/28 inside 2001::/23), Teredo (2001::/32, "N/A",
# inside 2001::/23) and the site-local fec0::/10 (RFC 3879), which ipaddress
# counts as global. IPv4-mapped, NAT64 and 6to4 are not listed: their embedded
# IPv4 address decides.
_NOT_GLOBAL = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "::/128",
        "::1/128",
        "64:ff9b:1::/48",
        "100::/64",
        "100:0:0:1::/64",
        "2001::/23",
        "2001:db8::/32",
        "3fff::/20",
        "5f00::/16",
        "fc00::/7",
        "fe80::/10",
        "fec0::/10",
    )
)


# RFC 7050 §2.2: the IPv4 addresses a DNS64 synthesises ipv4only.arpa from.
_WELL_KNOWN_V4 = (
    int(ipaddress.IPv4Address("192.0.0.170")),
    int(ipaddress.IPv4Address("192.0.0.171")),
)
# RFC 6052 §2.2: the prefix lengths a NAT64 prefix may have.
_PREFIX_LENGTHS = (32, 40, 48, 56, 64, 96)
NAT64_QUERY_LIFETIME_S = 2.0
# How long a learned answer and a failed lookup are kept. A failure is asked again
# soon: the resolver may not be up yet when the service starts.
NAT64_TTL_S = 600.0
NAT64_RETRY_S = 60.0

_nat64_lock = threading.Lock()
_nat64_cache: tuple[float, tuple[ipaddress.IPv6Network, ...]] | None = None


def _embedded_v4(value: int, length: int) -> int | None:
    """The 32 bits RFC 6052 §2.2 embeds after a prefix of `length`; None if the u octet is set."""
    if length == 96:
        return value & 0xFFFFFFFF
    if (value >> 56) & 0xFF:  # bits 64 to 71, the u octet, must be zero
        return None
    high_bits = 64 - length  # the part of the IPv4 address before the u octet
    high = (value >> 64) & ((1 << high_bits) - 1)
    low = (value >> (56 - (32 - high_bits))) & ((1 << (32 - high_bits)) - 1)
    return (high << (32 - high_bits)) | low


def nat64_prefixes_from(addresses: tuple[str, ...]) -> tuple[ipaddress.IPv6Network, ...]:
    """The NAT64 prefixes in the AAAA answers for ipv4only.arpa (RFC 7050 §3).

    The answers are searched for 192.0.0.170 first. If it sits at more than one
    position of an answer, or nowhere, the search is repeated with 192.0.0.171.
    """
    values = []
    for raw in addresses:
        try:
            values.append(int(ipaddress.IPv6Address(raw)))
        except ValueError:
            continue
    for well_known in _WELL_KNOWN_V4:
        prefixes: list[ipaddress.IPv6Network] = []
        for value in values:
            found = [n for n in _PREFIX_LENGTHS if _embedded_v4(value, n) == well_known]
            if len(found) > 1:
                break
            if found:
                prefix = ipaddress.IPv6Network((value, found[0]), strict=False)
                if prefix not in prefixes:
                    prefixes.append(prefix)
        else:
            if prefixes:
                return tuple(prefixes)
    return ()


def lookup_ipv4only() -> tuple[str, ...]:
    """Asks the system resolver for the AAAA records of ipv4only.arpa; tests replace this function.

    No answer (NXDOMAIN, NODATA) means no DNS64 and is no error; a timeout or a
    network error raises.
    """
    res = dns.resolver.Resolver()
    res.lifetime = NAT64_QUERY_LIFETIME_S
    try:
        answer = res.resolve(
            dns.name.from_text("ipv4only.arpa"), "AAAA", raise_on_no_answer=False, search=False
        )
    except dns.resolver.NXDOMAIN:
        return ()
    if answer.rrset is None:
        return ()
    return tuple(r.address for r in answer.rrset)


def nat64_prefixes() -> tuple[ipaddress.IPv6Network, ...]:
    """The NAT64 prefixes of this environment, learned once and kept for NAT64_TTL_S.

    A failed lookup keeps what was learned before: dropping it would judge the operator's own
    prefix global again until the resolver answers.
    """
    global _nat64_cache
    with _nat64_lock:
        now = time.monotonic()
        if _nat64_cache is not None and now < _nat64_cache[0]:
            return _nat64_cache[1]
        try:
            prefixes = nat64_prefixes_from(lookup_ipv4only())
            expires = now + NAT64_TTL_S
        except (dns.exception.DNSException, OSError):
            prefixes = _nat64_cache[1] if _nat64_cache is not None else ()
            expires = now + NAT64_RETRY_S
        _nat64_cache = (expires, prefixes)
        return prefixes


def effective_address(ip: IpAddress) -> IpAddress:
    """The address that decides: the embedded IPv4 of an IPv4-mapped, NAT64 or 6to4 address."""
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip in _NAT64:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if ip.sixtofour is not None:
            return ip.sixtofour
    return ip


def is_global_address(ip: IpAddress) -> bool:
    """True when a central check may treat `ip` as reachable from the internet."""
    if ip.version == 6 and ip.ipv4_mapped is None:
        for prefix in nat64_prefixes():
            if ip in prefix:
                v4 = _embedded_v4(int(ip), prefix.prefixlen)
                if v4 is None or not _is_global(ipaddress.IPv4Address(v4)):
                    return False
    return _is_global(ip)


def _is_global(ip: IpAddress) -> bool:
    ip = effective_address(ip)
    if any(ip in net for net in _GLOBAL):
        return True
    # ipaddress counts multicast as global; it is no endpoint to connect to.
    if ip.is_multicast or any(ip in net for net in _NOT_GLOBAL):
        return False
    if ip.version == 6 and ip not in _GLOBAL_UNICAST:
        return False
    return ip.is_global
