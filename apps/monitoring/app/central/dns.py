# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensor dns of central checks (R-1224): addresses, delegation, DNSSEC.

Every run compares the addresses the public resolvers gave the rule public/internal
(no second lookup) with each other and with a reference: the expected addresses of
the params, or else the baseline, the union of the first run in which every
resolver answered. Once an hour the sensor asks the name servers of the host's zone
directly whether they answer for it with authority, and, when the parent holds a DS
record for the zone, how long their signatures over the host still hold. Between
two of these looks the stored state gives the verdict, against the current time.
"""

from __future__ import annotations

import ipaddress
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import dns.exception
import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rdatatype

from app.central import resolve
from app.central.limits import LIMITS, Limits
from app.central.resolve import AnswerStatus, Classification, Reach
from app.central.tls import SensorResult
from app.core import config
from app.core.time import iso_utc

RECHECK = timedelta(hours=1)
RETRY = timedelta(minutes=15)
MAX_NAME_SERVERS = 8
ADDRESSES_PER_SERVER = 2
SERVER_WORKERS = 4
# The zone search climbs at most this many labels.
MAX_LABELS = 16
MAX_LISTED = 8
MAX_TEXT = 200
# Signers renew a signature well before it ends (BIND at 25 % of its validity left,
# Knot at about 10 %); below 5 % the renewal is overdue. Relative, as windows run
# from two days (online signers) to a month.
SIG_WARN_PCT = 5.0

_BOGUS = "bogus"
_SERVFAIL = "servfail"


class _NoLook(Exception):
    """The hourly look could not be made; the stored state stays."""


class _Asked:
    """The answers of one look by address: name servers that share an address ask it once
    (R-1381), so their number does not run the look into the spacing of that address."""

    def __init__(self, limits: Limits) -> None:
        self._limits = limits
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._soa: dict[str, dns.message.Message] = {}
        self._tries: dict[str, int] = {}
        self._sigs: dict[str, dict] = {}

    def _address(self, address: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(address, threading.Lock())

    def soa(self, address: str, zone: dns.name.Name) -> dns.message.Message | None:
        """The SOA reply of `address`; None without a reply after two questions in this look."""
        with self._address(address):
            if address in self._soa:
                return self._soa[address]
            if self._tries.get(address, 0) >= 2:
                return None
            if not self._limits.address_turn(address):
                raise _NoLook("name server spacing")
            self._tries[address] = self._tries.get(address, 0) + 1
            response = exchange(address, zone, "SOA", recursion=False)
            if response is not None:
                self._soa[address] = response
            return response

    def signature(
        self, address: str, zone: dns.name.Name, name: dns.name.Name, rdtype: str
    ) -> dict:
        with self._address(address):
            if address not in self._sigs:
                self._sigs[address] = _signature(address, zone, name, rdtype)
            return self._sigs[address]


def exchange(
    server: str,
    qname: dns.name.Name,
    rdtype: str,
    *,
    recursion: bool = True,
    checking_disabled: bool = False,
    dnssec: bool = False,
) -> dns.message.Message | None:
    """One question to `server`; None without a reply. Tests replace this function."""
    query = dns.message.make_query(qname, rdtype, use_edns=0, want_dnssec=dnssec)
    if not recursion:
        query.flags &= ~dns.flags.RD
    if checking_disabled:
        query.flags |= dns.flags.CD
    try:
        response, _ = dns.query.udp_with_fallback(query, server, timeout=resolve.QUERY_LIFETIME_S)
    except (dns.exception.DNSException, OSError, ValueError):
        return None
    return response


def probe(
    host: str,
    rule: Classification,
    params: dict,
    prev: dict | None = None,
    *,
    now: datetime | None = None,
    limits: Limits | None = None,
    resolvers: tuple[str, ...] | None = None,
) -> SensorResult:
    """The verdict on `host`, which the rule found public; `prev` holds the previous details."""
    now = now or datetime.now(timezone.utc)
    prev = prev or {}
    resolvers = resolvers or config.PUBLIC_RESOLVERS
    findings: list[tuple[str, str]] = []
    details: dict = {"host": host}
    metrics: dict = {}

    sets = {
        a.resolver: frozenset(_normal(x) for x in a.addresses)
        for a in rule.answers
        if a.status is AnswerStatus.OK
    }
    details["answers"] = {r: _sorted(s) for r, s in sets.items()}
    if len(sets) >= 2:
        agree = len(set(sets.values())) == 1
        metrics["resolvers_agree"] = 1.0 if agree else 0.0
        if not agree:
            seen = "; ".join(f"{r}: {_listed(s)}" for r, s in sets.items())
            findings.append(("warning", f"resolvers disagree ({seen})"))

    current = frozenset().union(*sets.values())
    complete = all(a.status is not AnswerStatus.SILENT for a in rule.answers)
    reference = _expected(params)
    if reference is None:
        baseline = _baseline(prev)
        if baseline is None and complete and current:
            baseline = {"addresses": _sorted(current), "since": iso_utc(now)}
        if baseline is not None:
            details["baseline"] = baseline
            reference = frozenset(baseline["addresses"])
    if reference is not None:
        added = current - reference
        # A silent resolver may hold the ones missing from the others' answers.
        removed = reference - current if complete else frozenset()
        if added or removed:
            findings.append(("warning", f"addresses changed: {_change(added, removed)}"))

    for answer in rule.answers:
        if answer.status is AnswerStatus.SILENT:
            verdict = _silence(answer.resolver, dns.name.from_text(host))
            if verdict == _BOGUS:
                findings.append(
                    (
                        "critical",
                        f"DNSSEC validation fails at resolver {answer.resolver}: "
                        "it answers only with checking disabled",
                    )
                )
            elif verdict == _SERVFAIL:
                findings.append(
                    ("warning", f"resolver {answer.resolver} cannot resolve {host} (SERVFAIL)")
                )

    zone = _state(prev, "zone")
    due = _parse_time((zone or {}).get("next_at"))
    if due is None or now >= due:
        rdtype = "A" if any(":" not in a for a in current) else "AAAA"
        zone = _look(host, rdtype, zone, now, limits or LIMITS, resolvers)
    details["zone"] = zone
    findings += _zone_findings(host, zone, now)

    if not findings:
        return SensorResult("ok", f"resolves to {_listed(current)}", True, metrics, details)
    status = "critical" if any(s == "critical" for s, _ in findings) else "warning"
    findings.sort(key=lambda f: f[0] != "critical")
    return SensorResult(status, "; ".join(t for _, t in findings), True, metrics, details)


def diagnose_silence(host: str, resolvers: tuple[str, ...] | None = None) -> str | None:
    """Why no public resolver answered for `host`, when the name and not our way out is at fault."""
    try:
        name = dns.name.from_text(host)
    except (dns.exception.DNSException, UnicodeError):
        return None
    resolvers = resolvers or config.PUBLIC_RESOLVERS
    with ThreadPoolExecutor(max_workers=len(resolvers), thread_name_prefix="central-dns") as pool:
        verdicts = list(pool.map(lambda r: _silence(r, name), resolvers))
    if _BOGUS in verdicts:
        return "DNSSEC validation fails: the resolvers answer only with checking disabled"
    if verdicts and all(v == _SERVFAIL for v in verdicts):
        return f"{host} cannot be resolved (SERVFAIL)"
    return None


def _silence(resolver: str, name: dns.name.Name) -> str | None:
    """Bogus when the resolver fails without and answers with checking disabled (RFC 4035 §3.2.2)."""
    response = exchange(resolver, name, "A")
    if response is None or response.rcode() != dns.rcode.SERVFAIL:
        return None  # no reply, or it answers again: nothing to say
    checked = exchange(resolver, name, "A", checking_disabled=True)
    if checked is not None and checked.rcode() in (dns.rcode.NOERROR, dns.rcode.NXDOMAIN):
        return _BOGUS
    return _SERVFAIL


# --- the hourly look ---


def _look(
    host: str,
    rdtype: str,
    old: dict | None,
    now: datetime,
    limits: Limits,
    resolvers: tuple[str, ...],
) -> dict:
    """The zone's name servers and signatures now; on failure the old state, retried sooner."""
    try:
        name = dns.name.from_text(host)
        zone = find_zone(name, resolvers)
        servers = _name_servers(zone, resolvers)
        signed = _signed(zone, resolvers)
        asked = _Asked(limits)
        with ThreadPoolExecutor(
            max_workers=SERVER_WORKERS, thread_name_prefix="central-dns-ns"
        ) as pool:
            entries = list(
                pool.map(
                    lambda ns: _ask_server(ns, zone, name, rdtype, signed, asked, resolvers),
                    servers[:MAX_NAME_SERVERS],
                )
            )
    except _NoLook as exc:
        state = dict(old or {})
        state.update(
            checked_at=iso_utc(now), error=str(exc)[:MAX_TEXT], next_at=iso_utc(now + RETRY)
        )
        return state
    state = {
        "name": zone.to_text(omit_final_dot=True),
        "signed": signed,
        "servers": entries,
        "checked_at": iso_utc(now),
        "next_at": iso_utc(now + RECHECK),
    }
    if len(servers) > MAX_NAME_SERVERS:
        state["unchecked"] = len(servers) - MAX_NAME_SERVERS
    return state


def find_zone(name: dns.name.Name, resolvers: tuple[str, ...]) -> dns.name.Name:
    """The zone that holds `name`: its own SOA, or the one the answer's authority names.

    An alias lives in its parent's zone; the resolver's answer would name the zone
    of the alias target, so the search goes on with the parent.
    """
    for _ in range(MAX_LABELS):
        response = _ask_resolvers(resolvers, name, "SOA")
        aliased = any(r.name == name and r.rdtype == dns.rdatatype.CNAME for r in response.answer)
        if not aliased:
            if any(r.name == name and r.rdtype == dns.rdatatype.SOA for r in response.answer):
                return name
            for rrset in response.authority:
                if rrset.rdtype == dns.rdatatype.SOA and name.is_subdomain(rrset.name):
                    return rrset.name
        if name == dns.name.root:
            break
        name = name.parent()
    raise _NoLook("zone not found")


def _name_servers(zone: dns.name.Name, resolvers: tuple[str, ...]) -> list[str]:
    response = _ask_resolvers(resolvers, zone, "NS")
    names = {
        rdata.target.to_text(omit_final_dot=True).lower()
        for rrset in response.answer
        if rrset.name == zone and rrset.rdtype == dns.rdatatype.NS
        for rdata in rrset
    }
    if not names:
        raise _NoLook("no name servers listed")
    return sorted(names)


def _signed(zone: dns.name.Name, resolvers: tuple[str, ...]) -> bool:
    """Whether the parent holds a DS record for `zone`: only then is DNSSEC looked at."""
    response = _ask_resolvers(resolvers, zone, "DS")
    return any(r.name == zone and r.rdtype == dns.rdatatype.DS for r in response.answer)


def _ask_resolvers(
    resolvers: tuple[str, ...], name: dns.name.Name, rdtype: str
) -> dns.message.Message:
    for resolver in resolvers:
        response = exchange(resolver, name, rdtype)
        if response is not None and response.rcode() in (dns.rcode.NOERROR, dns.rcode.NXDOMAIN):
            return response
    raise _NoLook(resolve.RESOLVERS_UNREACHABLE_MESSAGE)


def _ask_server(
    server: str,
    zone: dns.name.Name,
    name: dns.name.Name,
    rdtype: str,
    signed: bool,
    asked: _Asked,
    resolvers: tuple[str, ...],
) -> dict:
    """One name server: does it answer for the zone with authority, and how long do its signatures hold?"""
    entry: dict = {"name": server}
    rule = resolve.classify(server, resolvers)
    if rule.reach is Reach.RESOLVERS_UNREACHABLE:
        raise _NoLook(rule.message)
    if rule.reach is Reach.NOT_PUBLIC:
        entry["state"] = "no_address"
        return entry
    addresses = rule.addresses[:ADDRESSES_PER_SERVER]
    # Two questions at most: the second address, or the first once more, so that one
    # lost datagram does not make a name server look dead.
    for address in (addresses * 2)[:2]:
        response = asked.soa(address, zone)
        if response is None:
            continue
        entry["address"] = address
        soa = [r for r in response.answer if r.name == zone and r.rdtype == dns.rdatatype.SOA]
        authoritative = bool(response.flags & dns.flags.AA)
        if response.rcode() != dns.rcode.NOERROR or not authoritative or not soa:
            entry["state"] = "lame"
            return entry
        entry["state"] = "ok"
        entry["serial"] = soa[0][0].serial
        if signed:
            entry.update(asked.signature(address, zone, name, rdtype))
        return entry
    entry["state"] = "silent"
    return entry


def _signature(address: str, zone: dns.name.Name, name: dns.name.Name, rdtype: str) -> dict:
    """The validity of the zone's earliest-ending signature over `name` at this server."""
    response = exchange(address, name, rdtype, recursion=False, dnssec=True)
    if response is None:
        return {}
    sigs = [
        rdata
        for rrset in response.answer
        if rrset.name == name and rrset.rdtype == dns.rdatatype.RRSIG
        for rdata in rrset
        if rdata.signer == zone
    ]
    if not sigs:
        return {"sig_missing": True}
    first = min(sigs, key=lambda s: s.expiration)
    return {
        "sig_expires": iso_utc(_from_epoch(first.expiration)),
        "sig_inception": iso_utc(_from_epoch(first.inception)),
    }


def _zone_findings(host: str, zone: dict | None, now: datetime) -> list[tuple[str, str]]:
    servers = [s for s in (zone or {}).get("servers") or [] if isinstance(s, dict)]
    if not servers:
        return []
    name = zone.get("name") if isinstance(zone, dict) else None
    findings: list[tuple[str, str]] = []
    by_state: dict[str, list[dict]] = {}
    for server in servers:
        by_state.setdefault(server.get("state"), []).append(server)
    if "lame" in by_state:
        findings.append(
            (
                "warning",
                f"{_names(by_state['lame'])} not authoritative for {name} (lame delegation)",
            )
        )
    if "no_address" in by_state:
        findings.append(("warning", f"{_names(by_state['no_address'])} without a global address"))
    # Not one answer, from any server: our way out on port 53 is the likelier cause.
    if "silent" in by_state and len(by_state) > 1:
        findings.append(("warning", f"{_names(by_state['silent'])} not answering"))
    if zone.get("signed"):
        findings += _signature_findings(host, by_state.get("ok", []), now)
    return findings


def _signature_findings(host: str, servers: list[dict], now: datetime) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    missing = [s for s in servers if s.get("sig_missing")]
    if missing:
        findings.append(("warning", f"{_names(missing)} serving {host} unsigned in a signed zone"))
    expired: list[dict] = []
    ending: list[dict] = []
    for server in servers:
        expires = _parse_time(server.get("sig_expires"))
        inception = _parse_time(server.get("sig_inception"))
        if expires is None or inception is None:
            continue
        if expires <= now:
            expired.append(server)
        elif expires - now < (expires - inception) * (SIG_WARN_PCT / 100):
            ending.append(server)
    if expired:
        first = min(expired, key=lambda s: s["sig_expires"])
        findings.append(
            (
                "critical",
                f"DNSSEC signature over {host} expired {first['sig_expires']} at {_names(expired)}",
            )
        )
    if ending:
        first = min(ending, key=lambda s: s["sig_expires"])
        findings.append(
            (
                "warning",
                f"DNSSEC signature over {host} ends {first['sig_expires']} "
                f"at {_names(ending)}, not renewed",
            )
        )
    return findings


# --- helpers ---


def _expected(params: dict) -> frozenset[str] | None:
    raw = params.get("expected") if isinstance(params, dict) else None
    if not isinstance(raw, list):
        return None
    addresses = {_normal(a) for a in raw if isinstance(a, str) and _is_ip(a)}
    return frozenset(addresses) or None


def _baseline(prev: dict) -> dict | None:
    baseline = prev.get("baseline")
    if not isinstance(baseline, dict) or not isinstance(baseline.get("addresses"), list):
        return None
    addresses = [_normal(a) for a in baseline["addresses"] if isinstance(a, str) and _is_ip(a)]
    if not addresses:
        return None
    return {"addresses": _sorted(addresses), "since": baseline.get("since")}


def _state(prev: dict, key: str) -> dict | None:
    state = prev.get(key)
    return state if isinstance(state, dict) else None


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _normal(address: str) -> str:
    return str(ipaddress.ip_address(address))


def _sorted(addresses) -> list[str]:
    return sorted(addresses, key=lambda a: (":" in a, ipaddress.ip_address(a).packed))


def _listed(addresses) -> str:
    items = _sorted(addresses)
    shown = ", ".join(items[:MAX_LISTED])
    return shown + (f" (+{len(items) - MAX_LISTED})" if len(items) > MAX_LISTED else "")


def _change(added: frozenset[str], removed: frozenset[str]) -> str:
    parts = []
    if added:
        parts.append(f"new {_listed(added)}")
    if removed:
        parts.append(f"gone {_listed(removed)}")
    return "; ".join(parts)


def _names(servers: list[dict]) -> str:
    names = [str(s.get("name")) for s in servers]
    shown = ", ".join(names[:3])
    more = f" and {len(names) - 3} more" if len(names) > 3 else ""
    return f"name server{'s' if len(names) > 1 else ''} {shown}{more}"


def _from_epoch(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None
