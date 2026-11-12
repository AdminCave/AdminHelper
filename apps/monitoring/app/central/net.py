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
"""

from __future__ import annotations

import ipaddress

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
    ip = effective_address(ip)
    if any(ip in net for net in _GLOBAL):
        return True
    # ipaddress counts multicast as global; it is no endpoint to connect to.
    if ip.is_multicast or any(ip in net for net in _NOT_GLOBAL):
        return False
    if ip.version == 6 and ip not in _GLOBAL_UNICAST:
        return False
    return ip.is_global
