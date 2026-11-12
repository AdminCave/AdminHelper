# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensor dnsbl of central checks (R-1224): the domain's own mail hosts on DNS blocklists.

The MX hosts of the domain and their IPv4 addresses come from the public resolvers,
like in mail_dns. The lists are asked over the system resolver, the way a mail server
asks them: PSBL, SpamCop and UCEPROTECT level 1 are free to query, Spamhaus ZEN only
over its Data Query Service with the operator's key (MONITOR_SPAMHAUS_DQS_KEY), since
Spamhaus refuses queries from public resolvers. Only IPv4 addresses are looked up.

Every run first asks each list for its test entries (RFC 5782 §5): 127.0.0.2 must
be listed, 127.0.0.1 must not. A list that fails them, answers outside 127.0.0.0/8
or with an error code from 127.255.255.0/24 is not judged in this run and never
reads as "listed": a resolver that rewrites answers, or a list that went dark and
now lists the world, would otherwise raise a false alarm.

The DQS key is a label of the query name: no query name, no resolver error and no
exception leaves this module.
"""

from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import dns.exception
import dns.name
import dns.resolver

from app.central import maildns, resolve
from app.central.maildns import DnsAnswer
from app.central.net import is_global_address
from app.central.resolve import AnswerStatus
from app.central.tls import SensorResult
from app.core import config
from app.core.time import iso_utc

DEADLINE_S = 45.0
MAX_MX = 10
MAX_ADDRESSES = 10
MAX_TEXT = 200


@dataclass(frozen=True)
class Blocklist:
    title: str
    zone: str
    # Whether the TXT record of a listing is shown: the free lists name the reason
    # and where to ask for removal there.
    reason: bool = True


# The keys are the values of params.lists (check_configs.DnsblList).
LISTS: dict[str, Blocklist] = {
    "psbl": Blocklist("PSBL", "psbl.surriel.com"),
    "spamcop": Blocklist("SpamCop", "bl.spamcop.net"),
    "uceprotect1": Blocklist("UCEPROTECT level 1", "dnsbl-1.uceprotect.net"),
    "spamhaus_zen": Blocklist("Spamhaus ZEN", "zen.dq.spamhaus.net", reason=False),
}
FREE_LISTS = ("psbl", "spamcop", "uceprotect1")
NO_KEY_HINT = "Spamhaus ZEN skipped: no DQS key"

_LOOPBACK = ipaddress.ip_network("127.0.0.0/8")
# Spamhaus answers errors (bad key, public resolver, too many queries) from here.
_ERROR_CODES = ipaddress.ip_network("127.255.255.0/24")


def list_query(name: str, rdtype: str) -> DnsAnswer:
    """Asks the system resolver for the A or TXT records of `name`; tests replace this function."""
    try:
        res = dns.resolver.Resolver()
        res.lifetime = resolve.QUERY_LIFETIME_S
        answer = res.resolve(
            dns.name.from_text(name), rdtype, raise_on_no_answer=False, search=False
        )
    except dns.resolver.NXDOMAIN:
        return DnsAnswer(AnswerStatus.NXDOMAIN)
    except (dns.exception.DNSException, OSError):
        return DnsAnswer(AnswerStatus.SILENT)
    if answer.rrset is None:
        return DnsAnswer(AnswerStatus.NODATA)
    if rdtype == "TXT":
        values = tuple(b"".join(r.strings).decode("ascii", "replace") for r in answer.rrset)
    else:
        values = tuple(r.address for r in answer.rrset)
    return DnsAnswer(AnswerStatus.OK, values)


class _NotJudged(Exception):
    """A list or a mail host cannot be judged in this run; the text names why."""


class _Run:
    def __init__(self, resolvers: tuple[str, ...]) -> None:
        self.resolvers = resolvers
        self.deadline = time.monotonic() + DEADLINE_S

    def _check_time(self) -> None:
        if time.monotonic() >= self.deadline:
            raise _NotJudged(f"run longer than {DEADLINE_S:g} s")

    def public(self, name: str, rdtype: str) -> DnsAnswer:
        for resolver in self.resolvers:
            self._check_time()
            answer = maildns.query(resolver, name, rdtype)
            if answer.status is not AnswerStatus.SILENT:
                return answer
        raise _NotJudged(resolve.RESOLVERS_UNREACHABLE_MESSAGE)

    def listed(self, name: str, rdtype: str = "A") -> DnsAnswer:
        self._check_time()
        try:
            answer = list_query(name, rdtype)
        except Exception:  # the name may carry the DQS key: nothing leaves with it
            answer = DnsAnswer(AnswerStatus.SILENT)
        if answer.status is AnswerStatus.SILENT:
            raise _NotJudged("no answer")
        return answer


@dataclass
class _Findings:
    listed: list[dict] = field(default_factory=list)
    not_judged: list[tuple[str, str]] = field(default_factory=list)
    clean: list[str] = field(default_factory=list)
    # Mail hosts whose addresses no resolver gave: the run cannot vouch for them.
    gaps: list[str] = field(default_factory=list)


def probe(
    host: str,
    params: dict,
    prev: dict | None = None,
    *,
    now: datetime | None = None,
    resolvers: tuple[str, ...] | None = None,
) -> SensorResult:
    """Whether the IPv4 addresses of the MX hosts of `host` are on the chosen lists."""
    now = now or datetime.now(timezone.utc)
    domain = host.lower().rstrip(".")
    names, hints = _chosen(params)
    details: dict = {"domain": domain, "lists": names}
    if not names:
        return _result("unknown", "; ".join(hints), True, details, now)
    run = _Run(resolvers or config.PUBLIC_RESOLVERS)
    found = _Findings()
    try:
        addresses = _mx_addresses(run, domain, details, hints, found)
    except _NotJudged as exc:
        return _result("unknown", f"{domain}: {exc}", False, details, now)
    if not addresses:
        return _result("unknown", "; ".join([*found.gaps, *hints]), True, details, now)

    for name in names:
        _ask_list(run, name, addresses, found)
    details["listed"] = found.listed
    details["not_judged"] = [{"list": n, "reason": r} for n, r in found.not_judged]
    judged = [LISTS[n].title for n in found.clean]
    not_judged = [f"{LISTS[n].title} not judged: {r}" for n, r in found.not_judged] + found.gaps
    count = len(found.listed)
    clean = f"{len(addresses)} {_plural(len(addresses))} not listed on {', '.join(judged)}"
    if found.listed:
        message = "; ".join([_listings(found.listed), *not_judged, *hints])
        return _result("warning", message, True, details, now, count)
    if not_judged:
        message = "; ".join([*not_judged, *([clean] if judged else []), *hints])
        return _result("unknown", message, True, details, now)
    return _result("ok", "; ".join([clean, *hints]), True, details, now, count)


def _chosen(params: dict) -> tuple[list[str], list[str]]:
    """The lists of this run and the hints about the ones left out."""
    wanted = params.get("lists")
    if not isinstance(wanted, list) or not wanted:
        wanted = [*FREE_LISTS, *(["spamhaus_zen"] if config.SPAMHAUS_DQS_KEY else [])]
    names = [n for n in dict.fromkeys(wanted) if n in LISTS]
    if "spamhaus_zen" in names and not config.SPAMHAUS_DQS_KEY:
        names.remove("spamhaus_zen")
        return names, [NO_KEY_HINT]
    return names, []


def _mx_addresses(
    run: _Run, domain: str, details: dict, hints: list[str], found: _Findings
) -> list[str]:
    """The global IPv4 addresses of the MX hosts; an empty list leaves the reason in
    `hints` or `found.gaps`."""
    mx = run.public(domain, "MX")
    if mx.status is AnswerStatus.NXDOMAIN:
        hints.insert(0, f"{domain} is unknown to the public resolvers")
        return []
    if mx.status is AnswerStatus.OK:
        hosts = list(dict.fromkeys(h for _, h in sorted(mx.values) if h))
        if not hosts:
            details["mx"] = []
            hints.insert(0, f"null MX: {domain} receives no mail")
            return []
    else:
        # RFC 5321 §5.1: without an MX record the domain's own address takes mail.
        hosts = [domain]
    if len(hosts) > MAX_MX:
        hints.append(f"{len(hosts)} MX hosts, the first {MAX_MX} checked")
    details["mx"] = [_show(h) for h in hosts[:MAX_MX]]
    addresses: list[str] = []
    for mx_host in hosts[:MAX_MX]:
        try:
            answer = run.public(mx_host, "A")
        except _NotJudged as exc:
            found.gaps.append(f"MX {_show(mx_host)} not judged: {exc}")
            continue
        for value in answer.values if answer.status is AnswerStatus.OK else ():
            try:
                address = ipaddress.IPv4Address(value)
            except ValueError:
                continue
            if is_global_address(address) and str(address) not in addresses:
                addresses.append(str(address))
    if len(addresses) > MAX_ADDRESSES:
        hints.append(f"{len(addresses)} addresses, the first {MAX_ADDRESSES} checked")
    details["addresses"] = addresses[:MAX_ADDRESSES]
    if not addresses and not found.gaps:
        hints.insert(0, "no global IPv4 address of the mail hosts: the lists are asked for IPv4")
    return addresses[:MAX_ADDRESSES]


def _ask_list(run: _Run, name: str, addresses: list[str], found: _Findings) -> None:
    blocklist = LISTS[name]
    zone = blocklist.zone
    if name == "spamhaus_zen":
        zone = f"{config.SPAMHAUS_DQS_KEY}.{zone}"
    listed: list[dict] = []
    try:
        if _codes(run.listed(f"2.0.0.127.{zone}")) is None:
            raise _NotJudged("test entry 127.0.0.2 not listed (RFC 5782 §5)")
        if _codes(run.listed(f"1.0.0.127.{zone}")) is not None:
            raise _NotJudged("127.0.0.1 listed, which no list may (RFC 5782 §5)")
        for address in addresses:
            query = f"{_reversed(address)}.{zone}"
            codes = _codes(run.listed(query))
            if codes is None:
                continue
            entry = {"address": address, "list": name, "codes": list(codes)}
            if blocklist.reason:
                entry["reason"] = _reason(run, query)
            listed.append(entry)
    except _NotJudged as exc:
        found.not_judged.append((name, str(exc)))
        return
    found.listed.extend(listed)
    if not listed:
        found.clean.append(name)


def _codes(answer: DnsAnswer) -> tuple[str, ...] | None:
    """The return codes of a listing; None when not listed. Raises _NotJudged for any
    other answer."""
    if answer.status in (AnswerStatus.NXDOMAIN, AnswerStatus.NODATA) or not answer.values:
        return None
    codes = []
    for value in answer.values:
        try:
            code = ipaddress.IPv4Address(value)
        except ValueError:
            raise _NotJudged("answer outside 127.0.0.0/8") from None
        if code not in _LOOPBACK:
            raise _NotJudged("answer outside 127.0.0.0/8")
        if code in _ERROR_CODES:
            raise _NotJudged(f"error code {code}")
        codes.append(str(code))
    return tuple(sorted(codes, key=ipaddress.IPv4Address))


def _reason(run: _Run, query: str) -> str:
    try:
        answer = run.listed(query, "TXT")
    except _NotJudged:
        return ""
    values = answer.values if answer.status is AnswerStatus.OK else ()
    return _show(values[0]) if values else ""


def _listings(listed: list[dict]) -> str:
    by_address: dict[str, list[str]] = {}
    for entry in listed:
        codes = ", ".join(entry["codes"])
        by_address.setdefault(entry["address"], []).append(
            f"{LISTS[entry['list']].title} ({codes})"
        )
    return "; ".join(f"{a} listed on {', '.join(lists)}" for a, lists in by_address.items())


def _result(
    status: str,
    message: str,
    reached: bool,
    details: dict,
    now: datetime,
    listed_count: int | None = None,
) -> SensorResult:
    details["checked_at"] = iso_utc(now)
    metrics = {} if listed_count is None else {"listed_count": listed_count}
    return SensorResult(status, message, reached, metrics=metrics, details={"dnsbl": details})


def _reversed(address: str) -> str:
    return ".".join(reversed(address.split(".")))


def _plural(n: int) -> str:
    return "address" if n == 1 else "addresses"


def _show(text: str) -> str:
    """Text from DNS as messages and details may carry it."""
    return "".join(c if c.isprintable() else "?" for c in text[: MAX_TEXT * 2])[:MAX_TEXT]
