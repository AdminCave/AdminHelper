# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rule public/internal for central checks (R-1224, concept §3.7).

A target is public when the public resolvers, asked directly and not through the
system resolver, know its name and at least one of its addresses is global. Only
the global addresses are handed on: a central check connects to these and to
nothing else, so no second lookup can lead it elsewhere.
"""

from __future__ import annotations

import enum
import ipaddress
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import dns.exception
import dns.name
import dns.resolver

from app.central.net import effective_address, is_global_address
from app.core import config

# One question to one resolver; a resolver asks two (A and AAAA). The resolvers are
# asked in parallel, so a dead one costs about twice this, not twice per resolver.
QUERY_LIFETIME_S = 2.0

NOT_PUBLIC_MESSAGE = "not public – checked by the agent"
RESOLVERS_UNREACHABLE_MESSAGE = "public resolvers unreachable"


class AnswerStatus(enum.Enum):
    OK = "ok"
    NXDOMAIN = "nxdomain"
    NODATA = "nodata"
    # No usable answer: timeout, network error, SERVFAIL or REFUSED.
    SILENT = "silent"


@dataclass(frozen=True)
class ResolverAnswer:
    resolver: str
    status: AnswerStatus
    addresses: tuple[str, ...] = ()


class Reach(enum.Enum):
    PUBLIC = "public"
    NOT_PUBLIC = "not_public"
    RESOLVERS_UNREACHABLE = "resolvers_unreachable"


@dataclass(frozen=True)
class Classification:
    """What the rule says about one host.

    `addresses` holds, for PUBLIC only, the global addresses in resolver order
    without duplicates. `notes` say why, for the check's message and details.
    """

    reach: Reach
    addresses: tuple[str, ...] = ()
    answers: tuple[ResolverAnswer, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        if self.reach is Reach.NOT_PUBLIC:
            return NOT_PUBLIC_MESSAGE
        if self.reach is Reach.RESOLVERS_UNREACHABLE:
            return RESOLVERS_UNREACHABLE_MESSAGE
        return ""


def query(resolver: str, name: dns.name.Name, rdtype: str) -> ResolverAnswer:
    """Asks `resolver` for the `rdtype` records of `name`; tests replace this function."""
    res = dns.resolver.Resolver(configure=False)
    res.nameservers = [resolver]
    res.lifetime = QUERY_LIFETIME_S
    try:
        answer = res.resolve(name, rdtype, raise_on_no_answer=False, search=False)
    except dns.resolver.NXDOMAIN:
        return ResolverAnswer(resolver, AnswerStatus.NXDOMAIN)
    except (dns.exception.DNSException, OSError):
        return ResolverAnswer(resolver, AnswerStatus.SILENT)
    if answer.rrset is None:
        return ResolverAnswer(resolver, AnswerStatus.NODATA)
    return ResolverAnswer(resolver, AnswerStatus.OK, tuple(rdata.address for rdata in answer.rrset))


def ask(resolver: str, name: dns.name.Name) -> ResolverAnswer:
    """The A and AAAA answers of one resolver as one.

    Addresses from either question make it OK. Otherwise a known-missing name
    outranks silence (the resolver did answer), and silence outranks "no data": a
    name without A records says nothing about AAAA records that timed out.
    """
    parts = [query(resolver, name, "A"), query(resolver, name, "AAAA")]
    addresses = tuple(a for part in parts for a in part.addresses)
    if addresses:
        return ResolverAnswer(resolver, AnswerStatus.OK, addresses)
    for status in (AnswerStatus.NXDOMAIN, AnswerStatus.SILENT):
        if any(part.status is status for part in parts):
            return ResolverAnswer(resolver, status)
    return ResolverAnswer(resolver, AnswerStatus.NODATA)


def classify(host: str, resolvers: tuple[str, ...] | None = None) -> Classification:
    """Applies the rule public/internal to `host`, a name or an IP literal."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if is_global_address(literal):
            return Classification(Reach.PUBLIC, (_connect_form(literal),))
        return Classification(Reach.NOT_PUBLIC, notes=("not a global address",))
    try:
        name = dns.name.from_text(host)
    except (dns.exception.DNSException, UnicodeError):
        return Classification(Reach.NOT_PUBLIC, notes=("invalid host name",))

    resolvers = config.PUBLIC_RESOLVERS if resolvers is None else resolvers
    with ThreadPoolExecutor(max_workers=len(resolvers), thread_name_prefix="central-dns") as pool:
        answers = tuple(pool.map(lambda r: ask(r, name), resolvers))
    notes = [f"resolver {a.resolver} silent" for a in answers if a.status is AnswerStatus.SILENT]
    responding = [a for a in answers if a.status is not AnswerStatus.SILENT]
    if not responding:
        return Classification(Reach.RESOLVERS_UNREACHABLE, answers=answers, notes=tuple(notes))
    # A silent resolver does not veto: the rule decides on the ones that answered
    # (one resolver down is not the target's fault). Every one of those must know
    # the name with addresses, though.
    missing = [a for a in responding if a.status is not AnswerStatus.OK]
    if missing:
        notes += [f"resolver {a.resolver}: {_status_note(a.status)}" for a in missing]
        return Classification(Reach.NOT_PUBLIC, answers=answers, notes=tuple(notes))
    addresses: list[str] = []
    for answer in responding:
        for raw in answer.addresses:
            ip = ipaddress.ip_address(raw)
            if is_global_address(ip) and _connect_form(ip) not in addresses:
                addresses.append(_connect_form(ip))
    if not addresses:
        notes.append("no global address")
        return Classification(Reach.NOT_PUBLIC, answers=answers, notes=tuple(notes))
    return Classification(Reach.PUBLIC, tuple(addresses), answers, tuple(notes))


def _connect_form(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """An IPv4-mapped address as its IPv4 address; NAT64 and 6to4 stay IPv6, the path goes through them."""
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return str(effective_address(ip))
    return str(ip)


def _status_note(status: AnswerStatus) -> str:
    return "name unknown" if status is AnswerStatus.NXDOMAIN else "no address"
