# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensor mail_dns of central checks (R-1224): the mail records of a domain as receivers see them.

Asked over the public resolvers directly, like the rule public/internal, and like a
registry sensor without connecting to the domain's mail hosts: a mail-only domain
has no address of its own. Six parts, each with a verdict of its own; the worst wins.

- MX: the mail hosts and their addresses (RFC 5321 §5.1, null MX RFC 7505).
- FCrDNS: each global MX address has a PTR record whose name resolves back to it.
- SPF (RFC 7208): exactly one record, its syntax, at most 10 DNS lookups and at
  most two void lookups over all include and redirect targets (§4.6.4). Counted
  statically for a sender no term matches, which is how every forged mail is
  evaluated; a term with macros is counted but not followed.
- DMARC (RFC 9989): the record of the domain, else the one the DNS Tree Walk finds
  (§4.10.1); p=none is only a hint.
- MTA-STS (RFC 8461): the TXT record and the policy over HTTPS from
  mta-sts.<domain>, fetched like every central request from a global address only;
  an MX host the policy does not name is critical in mode enforce.
- TLS-RPT (RFC 8460): the syntax of the record.

Record text comes from whoever controls the domain's DNS: every parser here runs
in linear time, splitting on fixed characters instead of on patterns with
overlapping repeats.
"""

from __future__ import annotations

import ipaddress
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import dns.exception
import dns.name
import dns.resolver
import dns.reversename

from app.central import fetch, resolve
from app.central.net import is_global_address
from app.central.resolve import AnswerStatus
from app.central.tls import SensorResult
from app.core import config
from app.core.time import iso_utc

# Bounds of one run: lookups, wall-clock time, MX hosts, addresses for FCrDNS and
# PTR names per address. A domain beyond them is judged on what fits.
MAX_LOOKUPS = 150
DEADLINE_S = 45.0
MAX_MX = 10
MAX_ADDRESSES = 10
MAX_PTR_NAMES = 3
MAX_TEXT = 200
MAX_RECORD = 512
SPF_MAX_LOOKUPS = 10
SPF_MAX_VOID = 2
SPF_MAX_MX = 10
# RFC 9989 §4.10: a walk asks at most eight names.
DMARC_MAX_LABELS = 8
MTA_STS_MAX_AGE = 31557600

_LEVELS = ("critical", "warning")
_WSP = " \t"

# RFC 7208 §12. A macro-expand starts with "%", a literal never does, so the
# alternation never backtracks.
_MACRO_EXPAND = r"%\{[slodiphcrtvSLODIPHCRTV][0-9]*[rR]?[.\-+,/_=]*\}|%[%_-]"
_MACRO_STRING = re.compile(rf"(?:{_MACRO_EXPAND}|[\x21-\x24\x26-\x7e])*")
_MACRO_TOKEN = re.compile(rf"{_MACRO_EXPAND}|[^%]")
_MODIFIER = re.compile(r"([A-Za-z][A-Za-z0-9_.-]*)=(.*)", re.S)
_DIRECTIVE = re.compile(r"([+?~-]?)([A-Za-z][A-Za-z0-9_.-]*)(.*)", re.S)
_DUAL_CIDR = re.compile(r"(?:/(0|[1-9][0-9]?))?(?://(0|[1-9][0-9]{0,2}))?\Z")
_SPF_VERSION = re.compile(r"v=spf1(?: |\Z)", re.I)
_LOOKUP_TERMS = ("include", "a", "mx", "ptr", "exists")

_DMARC_VERSION = re.compile(r"[vV][ \t]*=[ \t]*DMARC1[ \t]*(?:;|\Z)")
_DMARC_TAG = re.compile(r"([A-Za-z]+)[ \t]*=(.*)", re.S)
_DMARC_VALUE = re.compile(r"[\x20-\x3a\x3c-\x7e]+")
_DMARC_POLICIES = ("none", "quarantine", "reject")
# RFC 3986 URI characters without the comma and "!" DMARC wants encoded.
_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[A-Za-z0-9\-._~%:@/?#\[\]$&'()*+=]+")
_OBSOLETE_SIZE = re.compile(r"![0-9]+[kmgtKMGT]?\Z")

# RFC 8461 §3.1 and RFC 8460 §3: fields separated by *WSP ";" *WSP.
_EXT_FIELD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}=[\x21-\x3a\x3c\x3e-\x7e]+")
_STS_ID = re.compile(r"id=[A-Za-z0-9]{1,32}")
_RPT_URI = r"(?:[mM][aA][iI][lL][tT][oO]|[hH][tT][tT][pP][sS]):[A-Za-z0-9\-._~%:@/?#\[\]$&'()*+=]+"
_TLS_RPT_RUA = re.compile(rf"rua={_RPT_URI}(?:[ \t]*,[ \t]*{_RPT_URI})*")
_POLICY_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
_HOSTNAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


@dataclass(frozen=True)
class DnsAnswer:
    status: AnswerStatus
    # TXT: the record's strings joined without spaces (RFC 7208 §3.3); MX:
    # (preference, host) with "" for the root; A, AAAA: addresses; PTR: names.
    values: tuple = ()


class _NoStatement(Exception):
    """A part cannot be judged: no resolver answered, or the run's bounds are spent."""


class _SpfError(Exception):
    """A receiver evaluating the record ends in permerror."""


def query(resolver: str, name: str, rdtype: str) -> DnsAnswer:
    """Asks `resolver` for the `rdtype` records of `name`; tests replace this function."""
    res = dns.resolver.Resolver(configure=False)
    res.nameservers = [resolver]
    res.lifetime = resolve.QUERY_LIFETIME_S
    try:
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
    elif rdtype == "MX":
        values = tuple((r.preference, _text(r.exchange)) for r in answer.rrset)
    elif rdtype == "PTR":
        values = tuple(_text(r.target) for r in answer.rrset)
    else:
        values = tuple(r.address for r in answer.rrset)
    return DnsAnswer(AnswerStatus.OK, values)


def _text(name: dns.name.Name) -> str:
    return "" if name == dns.name.root else name.to_text(omit_final_dot=True).lower()


class _Asker:
    """The lookups of one run: resolvers in order, each name and type asked once."""

    def __init__(self, resolvers: tuple[str, ...]) -> None:
        self.resolvers = resolvers
        self.deadline = time.monotonic() + DEADLINE_S
        self.count = 0
        self.cache: dict[tuple[str, str], DnsAnswer] = {}

    def __call__(self, name: str, rdtype: str) -> DnsAnswer:
        key = (name.lower().rstrip("."), rdtype)
        if key in self.cache:
            return self.cache[key]
        if not _dns_name(key[0]):
            # A name DNS cannot carry does not exist; no resolver is asked.
            return DnsAnswer(AnswerStatus.NXDOMAIN)
        for resolver in self.resolvers:
            if self.count >= MAX_LOOKUPS or time.monotonic() >= self.deadline:
                raise _NoStatement(f"more than {MAX_LOOKUPS} lookups or {DEADLINE_S:g} s")
            self.count += 1
            answer = query(resolver, key[0], rdtype)
            if answer.status is not AnswerStatus.SILENT:
                self.cache[key] = answer
                return answer
        raise _NoStatement(resolve.RESOLVERS_UNREACHABLE_MESSAGE)

    def txt(self, name: str) -> tuple[str, ...]:
        return _values(self(name, "TXT"))


@dataclass
class _Report:
    findings: list[tuple[str, str]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    silent: list[tuple[str, str]] = field(default_factory=list)
    good: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def add(self, level: str, text: str) -> None:
        if level in _LEVELS:
            self.findings.append((level, _show(text, MAX_TEXT * 2)))
        else:
            self.hints.append(_show(text, MAX_TEXT * 2))


def probe(
    host: str,
    params: dict,
    prev: dict | None = None,
    *,
    now: datetime | None = None,
    resolvers: tuple[str, ...] | None = None,
) -> SensorResult:
    """The verdict on the mail records of the domain `host`; the sensor keeps no state."""
    now = now or datetime.now(timezone.utc)
    domain = host.lower().rstrip(".")
    ask = _Asker(resolvers or config.PUBLIC_RESOLVERS)
    try:
        mx = ask(domain, "MX")
    except _NoStatement as exc:
        return SensorResult("unknown", f"{domain}: {exc}", False)
    if mx.status is AnswerStatus.NXDOMAIN:
        return SensorResult("unknown", f"{domain} is unknown to the public resolvers", True)

    report = _Report()
    hosts = _mx_hosts(domain, mx, report)
    addresses: dict[str, list[str]] = {}
    _part(report, "MX", lambda: addresses.update(_mx_addresses(ask, domain, hosts, report)))
    mx_silent = [reason for name, reason in report.silent if name == "MX"]
    if mx_silent:
        report.silent.append(("FCrDNS", mx_silent[0]))
    else:
        _part(report, "FCrDNS", lambda: _fcrdns(ask, addresses, report))
    _part(report, "SPF", lambda: _spf(ask, domain, report))
    _part(report, "DMARC", lambda: _dmarc(ask, domain, report))
    mta_sts = _part(report, "MTA-STS", lambda: _mta_sts(ask, domain, hosts, report))
    _part(report, "TLS-RPT", lambda: _tls_rpt(ask, domain, bool(mta_sts), report))

    report.details["checked_at"] = iso_utc(now)
    details = {"mail_dns": {"domain": domain, **report.details}}
    silent = [f"{name}: {reason}" for name, reason in report.silent]
    if report.findings:
        status = "critical" if any(lv == "critical" for lv, _ in report.findings) else "warning"
        report.findings.sort(key=lambda f: f[0] != "critical")
        texts = [t for _, t in report.findings] + silent
        return SensorResult(status, "; ".join(texts), True, details=details)
    if silent:
        return SensorResult("unknown", "; ".join(silent + report.good), True, details=details)
    return SensorResult("ok", "; ".join(report.good + report.hints), True, details=details)


def _part(report: _Report, name: str, run):
    try:
        return run()
    except _NoStatement as exc:
        report.silent.append((name, str(exc)))
        return None


def _show(text: str, limit: int = MAX_TEXT) -> str:
    """Text from DNS or HTTP as messages and details may carry it."""
    return "".join(c if c.isprintable() else "?" for c in text[: limit * 2])[:limit]


def _values(answer: DnsAnswer) -> tuple:
    return answer.values if answer.status is AnswerStatus.OK else ()


def _dns_name(name: str) -> bool:
    name = name.removesuffix(".")
    return 0 < len(name) <= 253 and all(0 < len(label) <= 63 for label in name.split("."))


# --- MX and FCrDNS -----------------------------------------------------------------


def _mx_hosts(domain: str, mx: DnsAnswer, report: _Report) -> list[str] | None:
    """The MX hosts by preference; None for a null MX, the domain for an implicit MX."""
    if mx.status is not AnswerStatus.OK:
        report.details["mx"] = []
        return [domain]
    records = sorted(set(mx.values))
    hosts = list(dict.fromkeys(h for _, h in records if h))
    if not hosts:
        report.add("hint", f"null MX: {domain} receives no mail")
        report.details["mx"] = [{"preference": p, "host": "."} for p, _ in records]
        return None
    if len(hosts) < len({h for _, h in records}):
        report.add("warning", "a null MX next to other MX records (RFC 7505 §3)")
    if len(hosts) > MAX_MX:
        report.add("hint", f"{len(hosts)} MX hosts, the first {MAX_MX} checked")
    report.details["mx"] = [{"preference": p, "host": _show(h)} for p, h in records if h][:MAX_MX]
    return hosts[:MAX_MX]


def _mx_addresses(
    ask: _Asker, domain: str, hosts: list[str] | None, report: _Report
) -> dict[str, list[str]]:
    if not hosts:
        return {}
    found = {h: [a for rdtype in ("A", "AAAA") for a in _values(ask(h, rdtype))] for h in hosts}
    report.details["mx_addresses"] = {_show(h): a[:MAX_ADDRESSES] for h, a in found.items()}
    if hosts == [domain] and not found[domain]:
        report.add(
            "warning",
            f"{domain} has no MX record and no address: without a null MX (RFC 7505) "
            "senders retry for days",
        )
        return found
    if hosts == [domain]:
        report.add("hint", f"no MX record, mail goes to the address of {domain}")
    usable = False
    for host, addresses in found.items():
        if not addresses:
            report.add("warning", f"MX {host} has no address")
        elif not any(_global(a) for a in addresses):
            report.add("warning", f"MX {host} has no global address")
        else:
            usable = True
    if usable:
        report.good.append(f"{len(hosts)} MX")
    else:
        report.add("critical", f"no MX host of {domain} has a global address: no mail arrives")
    return found


def _fcrdns(ask: _Asker, addresses: dict[str, list[str]], report: _Report) -> None:
    candidates = list(dict.fromkeys(a for found in addresses.values() for a in found if _global(a)))
    if not candidates:
        return
    results: dict[str, str] = {}
    clean = True
    for address in candidates[:MAX_ADDRESSES]:
        reverse = dns.reversename.from_address(address).to_text(omit_final_dot=True)
        names = _values(ask(reverse, "PTR"))[:MAX_PTR_NAMES]
        if not names:
            report.add("warning", f"{address} has no PTR record")
            results[address] = ""
            clean = False
            continue
        wanted = ipaddress.ip_address(address)
        rdtype = "A" if wanted.version == 4 else "AAAA"
        results[address] = _show(names[0])
        if not any(wanted in _addresses(ask(name, rdtype)) for name in names):
            report.add("warning", f"{address}: PTR {names[0]} does not resolve back to it")
            clean = False
    report.details["fcrdns"] = results
    if clean:
        report.good.append("FCrDNS")


def _addresses(answer: DnsAnswer) -> set:
    found = set()
    for value in _values(answer):
        try:
            found.add(ipaddress.ip_address(value))
        except ValueError:
            continue
    return found


def _global(address: str) -> bool:
    try:
        return is_global_address(ipaddress.ip_address(address))
    except ValueError:
        return False


# --- SPF ---------------------------------------------------------------------------


@dataclass
class _SpfWalk:
    ask: _Asker
    lookups: int = 0
    # Void lookups as an IPv4 and as an IPv6 sender meets them: "a" asks for one type.
    void4: int = 0
    void6: int = 0

    def count(self) -> None:
        self.lookups += 1
        if self.lookups > SPF_MAX_LOOKUPS:
            raise _SpfError(f"more than {SPF_MAX_LOOKUPS} DNS lookups (RFC 7208 §4.6.4)")

    def void(self, v4: bool, v6: bool) -> None:
        self.void4 += v4
        self.void6 += v6
        if max(self.void4, self.void6) > SPF_MAX_VOID:
            raise _SpfError(f"more than {SPF_MAX_VOID} void lookups (RFC 7208 §4.6.4)")


def _spf(ask: _Asker, domain: str, report: _Report) -> None:
    records = _spf_records(ask, domain)
    if not records:
        report.add("warning", "no SPF record")
        return
    report.details["spf"] = {"record": _show(records[0], MAX_RECORD)}
    if len(records) > 1:
        report.add("critical", f"{len(records)} SPF records: receivers return permerror")
        return
    walk = _SpfWalk(ask)
    try:
        _spf_evaluate(walk, domain, records[0])
    except _SpfError as exc:
        report.add("critical", f"SPF: {exc}")
        return
    finally:
        report.details["spf"].update({"lookups": walk.lookups, "void": max(walk.void4, walk.void6)})
    report.good.append(f"SPF ({walk.lookups}/{SPF_MAX_LOOKUPS} lookups)")


def _spf_records(ask: _Asker, name: str) -> list[str]:
    return [r for r in ask.txt(name) if _SPF_VERSION.match(r)]


def _spf_evaluate(walk: _SpfWalk, name: str, record: str) -> None:
    terms = _spf_parse(record)
    redirect = None
    for kind, target, macro in terms:
        if kind == "all":
            # §5.1: terms after "all" are never tested, so they cost no lookup.
            break
        if kind == "redirect":
            redirect = (target, macro)
            continue
        if kind not in _LOOKUP_TERMS:
            continue
        walk.count()
        if macro:
            continue
        target = target or name
        if kind == "include":
            _spf_follow(walk, f"include:{target}", target)
        elif kind == "a":
            walk.void(not _values(walk.ask(target, "A")), not _values(walk.ask(target, "AAAA")))
        elif kind == "mx":
            hosts = _values(walk.ask(target, "MX"))
            if len(hosts) > SPF_MAX_MX:
                raise _SpfError(f"mx:{target} has more than {SPF_MAX_MX} MX records")
            walk.void(not hosts, not hosts)
        elif kind == "exists":
            # §5.7: the lookup is of type A, whatever the sender's address.
            empty = not _values(walk.ask(target, "A"))
            walk.void(empty, empty)
    # §6.1: redirect is ignored when the record has an "all" anywhere.
    if redirect is not None and not any(t[0] == "all" for t in terms):
        walk.count()
        if not redirect[1]:
            _spf_follow(walk, f"redirect={redirect[0]}", redirect[0])


def _spf_follow(walk: _SpfWalk, label: str, target: str) -> None:
    records = _spf_records(walk.ask, target)
    if not records:
        raise _SpfError(f"{label} has no SPF record")
    if len(records) > 1:
        raise _SpfError(f"{label} has {len(records)} SPF records")
    _spf_evaluate(walk, target, records[0])


def _spf_parse(record: str) -> list[tuple[str, str, bool]]:
    """The record's terms as (kind, domain, has macros); raises _SpfError on bad syntax."""
    terms: list[tuple[str, str, bool]] = []
    seen: set[str] = set()
    for term in record.split(" ")[1:]:
        if not term:
            continue
        modifier = _MODIFIER.fullmatch(term)
        if modifier:
            name, value = modifier.group(1).lower(), modifier.group(2)
            if name in ("redirect", "exp"):
                if name in seen:
                    raise _SpfError(f"{name}= more than once")
                seen.add(name)
                _spf_domain(value, term, exp=name == "exp")
                if name == "redirect":
                    terms.append(("redirect", value.lower().rstrip("."), "%" in value))
            elif not _MACRO_STRING.fullmatch(value):
                raise _SpfError(f"syntax error at '{_show(term)}'")
            continue
        directive = _DIRECTIVE.fullmatch(term)
        if not directive:
            raise _SpfError(f"syntax error at '{_show(term)}'")
        kind, rest = directive.group(2).lower(), directive.group(3)
        if kind not in ("all", "ip4", "ip6", *_LOOKUP_TERMS):
            raise _SpfError(f"unknown mechanism '{_show(term)}'")
        terms.append((kind, *_spf_argument(kind, rest, term)))
    return terms


def _spf_argument(kind: str, rest: str, term: str) -> tuple[str, bool]:
    if kind == "all":
        if rest:
            raise _SpfError(f"syntax error at '{_show(term)}'")
        return "", False
    if kind in ("ip4", "ip6"):
        _spf_network(kind, rest, term)
        return "", False
    if kind in ("a", "mx"):
        cidr = _DUAL_CIDR.search(rest)
        assert cidr is not None  # every group is optional
        v4, v6 = cidr.group(1), cidr.group(2)
        if (v4 and int(v4) > 32) or (v6 and int(v6) > 128):
            raise _SpfError(f"prefix length out of range at '{_show(term)}'")
        rest = rest[: cidr.start()]
    if not rest:
        if kind in ("include", "exists"):
            raise _SpfError(f"{kind} without a domain")
        return "", False
    if not rest.startswith(":"):
        raise _SpfError(f"syntax error at '{_show(term)}'")
    spec = rest[1:]
    _spf_domain(spec, term)
    return spec.lower().rstrip("."), "%" in spec


def _spf_network(kind: str, rest: str, term: str) -> None:
    if not rest.startswith(":"):
        raise _SpfError(f"invalid address at '{_show(term)}'")
    network, slash, length = rest[1:].partition("/")
    version = 4 if kind == "ip4" else 6
    try:
        # ipaddress takes an IPv6 scope ("%eth0"), RFC 4291 text knows none.
        if "%" in network or ipaddress.ip_address(network).version != version:
            raise ValueError(network)
    except ValueError:
        raise _SpfError(f"invalid address at '{_show(term)}'") from None
    if slash and not re.fullmatch(r"0|[1-9][0-9]{0,2}", length):
        raise _SpfError(f"invalid prefix length at '{_show(term)}'")
    if slash and int(length) > (32 if version == 4 else 128):
        raise _SpfError(f"prefix length out of range at '{_show(term)}'")


def _spf_domain(spec: str, term: str, *, exp: bool = False) -> None:
    """RFC 7208 §12 domain-spec: a macro-string ending in "." toplabel or in a macro-expand."""
    bad = _SpfError(f"invalid domain at '{_show(term)}'")
    if not _MACRO_STRING.fullmatch(spec):
        raise bad
    tokens = [t.group() for t in _MACRO_TOKEN.finditer(spec)]
    # §7.1: the macros c, r and t are for exp only.
    if not exp and any(t[:2] == "%{" and t[2] in "crtCRT" for t in tokens):
        raise bad
    if tokens and tokens[-1].startswith("%"):
        return
    _, dot, top = spec.removesuffix(".").rpartition(".")
    if not dot or not _toplabel(top):
        raise bad
    if "%" not in spec and not _dns_name(spec):
        raise bad


def _toplabel(label: str) -> bool:
    if not label or not all(c.isascii() and (c.isalnum() or c == "-") for c in label):
        return False
    if "-" in label:
        return label[0].isalnum() and label[-1].isalnum()
    return not label.isdigit()


# --- DMARC -------------------------------------------------------------------------


def _dmarc(ask: _Asker, domain: str, report: _Report) -> None:
    record = _dmarc_record(ask, domain, report)
    source = domain
    if record is None:
        found = _dmarc_walk(ask, domain, report)
        if found is None:
            report.add("warning", "no DMARC record: receivers apply no DMARC policy")
            return
        source, record = found
    name = f"_dmarc.{source}"
    report.details["dmarc"] = {"name": name, "record": _show(record, MAX_RECORD)}
    tags = _dmarc_tags(record)
    # §4.10.1: an inherited record applies its sp tag, if any, to the existing domain.
    key = "sp" if source != domain and "sp" in tags else "p"
    policy = tags.get(key, "none").lower()
    valid = policy in _DMARC_POLICIES and all(
        tags[k].lower() in _DMARC_POLICIES for k in ("p", "sp", "np") if k in tags
    )
    if not valid:
        if not _dmarc_rua(tags.get("rua", "")):
            report.add(
                "warning", f"{name}: invalid p, sp or np tag and no rua: DMARC is not applied"
            )
            return
        report.add("hint", f"{name}: invalid p, sp or np tag, receivers act as with p=none")
        policy = "none"
    report.details["dmarc"]["policy"] = policy
    where = "" if source == domain else f" from {source}"
    if policy == "none":
        report.add("hint", f"DMARC p=none{where}: receivers take no action")
    else:
        report.good.append(f"DMARC {key}={policy}{where}")


def _dmarc_record(ask: _Asker, name: str, report: _Report) -> str | None:
    records = [r for r in ask.txt(f"_dmarc.{name}") if _DMARC_VERSION.match(r)]
    if len(records) > 1:
        report.add("warning", f"{len(records)} DMARC records at _dmarc.{name}: all are ignored")
    return records[0] if len(records) == 1 else None


def _dmarc_walk(ask: _Asker, domain: str, report: _Report) -> tuple[str, str] | None:
    """RFC 9989 §4.10: the record that applies when the domain has none of its own."""
    labels = domain.split(".")
    labels = labels[1:] if len(labels) <= DMARC_MAX_LABELS else labels[-(DMARC_MAX_LABELS - 1) :]
    found: list[tuple[str, str, str]] = []
    while labels:
        name = ".".join(labels)
        record = _dmarc_record(ask, name, report)
        if record is not None:
            psd = _dmarc_tags(record).get("psd", "").lower()
            found.append((name, record, psd))
            if psd in ("y", "n"):
                break
        labels = labels[1:]
    # §4.10.2, longest name first: the Organizational Domain's record, else the PSD's.
    for name, record, psd in found:
        if psd == "n":
            return name, record
        if psd == "y":
            below = ".".join(domain.split(".")[-(name.count(".") + 2) :])
            for other, other_record, _ in found:
                if other == below:
                    return other, other_record
            return name, record
    return (found[-1][0], found[-1][1]) if found else None


def _dmarc_tags(record: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for part in record.split(";")[1:]:
        tag = _DMARC_TAG.fullmatch(part.strip(_WSP))
        if not tag:
            continue
        value = tag.group(2).strip(_WSP)
        if _DMARC_VALUE.fullmatch(value):
            tags.setdefault(tag.group(1).lower(), value)
    return tags


def _dmarc_rua(value: str) -> bool:
    for uri in value.split(","):
        uri = _OBSOLETE_SIZE.sub("", uri.strip(_WSP))
        if _URI.fullmatch(uri):
            return True
    return False


# --- MTA-STS and TLS-RPT -----------------------------------------------------------


def _mta_sts(ask: _Asker, domain: str, hosts: list[str] | None, report: _Report) -> bool:
    """Checks MTA-STS; True when the domain publishes a record."""
    records = [r for r in ask.txt(f"_mta-sts.{domain}") if r.startswith("v=STSv1;")]
    if not records:
        return False
    if len(records) > 1:
        report.add("warning", f"{len(records)} MTA-STS records: senders ignore MTA-STS")
        return True
    if not _fields_valid(records[0], "v=STSv1", _STS_ID):
        report.add("warning", "MTA-STS record invalid: senders ignore MTA-STS")
        return True
    url = f"https://mta-sts.{domain}/.well-known/mta-sts.txt"
    try:
        answer = fetch.get(url, accept="text/plain")
    except fetch.FetchError as exc:
        report.add("warning", f"MTA-STS policy not retrievable: {exc}")
        return True
    if answer.status != 200:
        report.add("warning", f"MTA-STS policy: HTTP {answer.status}")
        return True
    media = answer.content_type.split(";")[0].strip(_WSP).lower()
    if media != "text/plain":
        report.add("warning", f"MTA-STS policy served as {media or 'no type'}, not text/plain")
        return True
    policy, error = _sts_policy(answer.body)
    if error:
        report.add("warning", f"MTA-STS policy invalid: {error}")
        return True
    mode, patterns = policy["mode"], policy["mx"]
    report.details["mta_sts"] = {
        "mode": mode,
        "max_age": policy["max_age"],
        "mx": [_show(p) for p in patterns[:MAX_MX]],
    }
    if len(patterns) > MAX_MX:
        report.details["mta_sts"]["mx_count"] = len(patterns)
    if mode == "none":
        report.add("hint", "MTA-STS mode none")
        return True
    missing = [h for h in hosts or () if not any(_sts_match(p, h) for p in patterns)]
    for host in missing:
        if mode == "enforce":
            report.add("critical", f"MX {host} is not in the MTA-STS policy: senders refuse it")
        else:
            report.add("warning", f"MX {host} is not in the MTA-STS policy (mode testing)")
    if not missing:
        report.good.append(f"MTA-STS {mode}")
    return True


def _fields_valid(record: str, version: str, required: re.Pattern) -> bool:
    fields = [f.strip(_WSP) for f in record.split(";")]
    if fields[-1] == "":
        fields.pop()
    if len(fields) < 2 or fields[0] != version:
        return False
    rest = fields[1:]
    return any(required.fullmatch(f) for f in rest) and all(
        required.fullmatch(f) or _EXT_FIELD.fullmatch(f) for f in rest
    )


def _sts_policy(body: bytes) -> tuple[dict, str]:
    """The policy's mode, max_age and mx patterns, or an error (RFC 8461 §3.2)."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return {}, "not UTF-8"
    fields: dict[str, str] = {}
    patterns: list[str] = []
    for number, line in enumerate(text.split("\n"), 1):
        line = line.removesuffix("\r")
        if not line.strip(_WSP):
            continue
        key, colon, value = line.partition(":")
        value = value.strip(_WSP)
        if not colon or not _POLICY_KEY.fullmatch(key) or not value:
            return {}, f"line {number}"
        if not value.replace("\t", " ").isprintable():
            return {}, f"line {number}"
        if key == "mx":
            patterns.append(value.lower().rstrip("."))
        else:
            # §3.2: of a field other than mx, the first one counts.
            fields.setdefault(key, value)
    if fields.get("version") != "STSv1":
        return {}, "version is not STSv1"
    mode = fields.get("mode")
    if mode not in ("enforce", "testing", "none"):
        return {}, "mode is not enforce, testing or none"
    max_age = fields.get("max_age", "")
    if not re.fullmatch(r"[0-9]{1,10}", max_age) or int(max_age) > MTA_STS_MAX_AGE:
        return {}, f"max_age is no number up to {MTA_STS_MAX_AGE}"
    if mode != "none" and not patterns:
        return {}, "no mx line"
    if not all(_sts_pattern(p) for p in patterns):
        return {}, "an mx line is no host name"
    return {"mode": mode, "max_age": int(max_age), "mx": patterns}, ""


def _sts_pattern(pattern: str) -> bool:
    name = pattern.removeprefix("*.")
    return len(name) <= 253 and all(_HOSTNAME.fullmatch(x) for x in name.split("."))


def _sts_match(pattern: str, host: str) -> bool:
    """RFC 8461 §4.1: a wildcard stands for exactly the left-most label."""
    if pattern.startswith("*."):
        first, dot, rest = host.partition(".")
        return bool(first) and bool(dot) and rest == pattern[2:]
    return host == pattern


def _tls_rpt(ask: _Asker, domain: str, has_mta_sts: bool, report: _Report) -> None:
    records = [r for r in ask.txt(f"_smtp._tls.{domain}") if r.startswith("v=TLSRPTv1;")]
    if not records:
        if has_mta_sts:
            report.add("hint", "MTA-STS without TLS-RPT: no reports of failed deliveries")
        return
    if len(records) > 1:
        report.add("warning", f"{len(records)} TLS-RPT records: reporters ignore TLS-RPT")
        return
    if not _fields_valid(records[0], "v=TLSRPTv1", _TLS_RPT_RUA):
        report.add("warning", "TLS-RPT record invalid: reporters ignore it")
        return
    report.good.append("TLS-RPT")
