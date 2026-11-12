# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensor mail_dns of central checks (R-1224): the mail records of a domain.

The resolvers are a stand-in for maildns.query, the MTA-STS policy server one for
fetch.get; the HTTPS path itself is test_central_fetch.py. 198.51.100.0/24 stands
for addresses that are not global.
"""

import ipaddress
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import dns.resolver
import dns.reversename
import dns.rrset
import pytest

from app.central import fetch, maildns, resolve
from app.central.fetch import FetchError, HttpAnswer
from app.central.resolve import AnswerStatus

NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
R1, R2 = "192.0.2.53", "198.51.100.53"
RESOLVERS = (R1, R2)
D = "example.test"
MX1, MX2 = "mx1.example.test", "mx2.example.test"
NOT_GLOBAL = ipaddress.ip_network("198.51.100.0/24")
GOOD = "2 MX; FCrDNS; SPF (2/10 lookups); DMARC p=reject; MTA-STS enforce; TLS-RPT"


def _rev(address: str) -> str:
    return dns.reversename.from_address(address).to_text(omit_final_dot=True)


def _url(domain: str = D) -> str:
    return f"https://mta-sts.{domain}/.well-known/mta-sts.txt"


def _policy(mode="enforce", mx=(MX1, MX2), max_age="604800", *, extra=()) -> bytes:
    lines = ["version: STSv1", f"mode: {mode}", *(f"mx: {m}" for m in mx)]
    lines += [f"max_age: {max_age}", *extra]
    return "".join(f"{line}\r\n" for line in lines).encode()


def _page(body: bytes, content_type="text/plain; charset=utf-8", status=200) -> HttpAnswer:
    return HttpAnswer(status, None, body, content_type)


def base(domain: str = D) -> dict:
    """A domain whose mail records are all in order."""
    return {
        (domain, "MX"): [(10, MX1), (20, MX2)],
        (MX1, "A"): ["192.0.2.25"],
        (MX1, "AAAA"): ["2001:db8::25"],
        (MX2, "A"): ["192.0.2.26"],
        (_rev("192.0.2.25"), "PTR"): [MX1],
        (_rev("2001:db8::25"), "PTR"): [MX1],
        (_rev("192.0.2.26"), "PTR"): [MX2],
        (domain, "TXT"): ["v=spf1 mx include:_spf.mail.test -all", "site-verification=abc"],
        ("_spf.mail.test", "TXT"): ["v=spf1 ip4:192.0.2.0/24 ip6:2001:db8::/32 -all"],
        (f"_dmarc.{domain}", "TXT"): ["v=DMARC1; p=reject; rua=mailto:dmarc@example.test"],
        (f"_mta-sts.{domain}", "TXT"): ["v=STSv1; id=20261112"],
        (f"_smtp._tls.{domain}", "TXT"): ["v=TLSRPTv1; rua=mailto:tlsrpt@example.test"],
    }


class World:
    """maildns.query stand-in: records by (name, type); a name with records of other
    types, or below it, exists (NODATA), any other name does not (NXDOMAIN)."""

    def __init__(self, records):
        self.records = records
        self.silent: set[str] = set()
        self.silent_names: set[str] = set()
        self.asked: list[tuple[str, str, str]] = []

    def __call__(self, resolver, name, rdtype):
        self.asked.append((resolver, name, rdtype))
        if resolver in self.silent or name in self.silent_names:
            return maildns.DnsAnswer(AnswerStatus.SILENT)
        value = self.records.get((name, rdtype))
        if isinstance(value, AnswerStatus):
            return maildns.DnsAnswer(value)
        if value is not None:
            return maildns.DnsAnswer(AnswerStatus.OK, tuple(value))
        if any(n == name or n.endswith(f".{name}") for n, _ in self.records):
            return maildns.DnsAnswer(AnswerStatus.NODATA)
        return maildns.DnsAnswer(AnswerStatus.NXDOMAIN)

    @property
    def names(self) -> list[tuple[str, str]]:
        return [(name, rdtype) for _, name, rdtype in self.asked]


class Web:
    """fetch.get stand-in: answers by URL, 404 for any other."""

    def __init__(self, pages):
        self.pages = pages
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        answer = self.pages.get(url, _page(b"", "text/html", 404))
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture(autouse=True)
def _global(monkeypatch):
    monkeypatch.setattr(
        maildns, "is_global_address", lambda ip: not (ip.version == 4 and ip in NOT_GLOBAL)
    )


@pytest.fixture
def world(monkeypatch):
    stand_in = World(base())
    monkeypatch.setattr(maildns, "query", stand_in)
    return stand_in


@pytest.fixture
def web(monkeypatch):
    stand_in = Web({_url(): _page(_policy())})
    monkeypatch.setattr(fetch, "get", stand_in)
    return stand_in


def _probe(host=D):
    return maildns.probe(host, {}, None, now=NOW, resolvers=RESOLVERS)


# --- the whole run ------------------------------------------------------------------


def test_a_domain_in_order_is_ok_with_what_was_checked(world, web):
    result = _probe()

    assert (result.status, result.message, result.reached) == ("ok", GOOD, True)
    assert result.details == {
        "mail_dns": {
            "domain": D,
            "mx": [{"preference": 10, "host": MX1}, {"preference": 20, "host": MX2}],
            "mx_addresses": {MX1: ["192.0.2.25", "2001:db8::25"], MX2: ["192.0.2.26"]},
            "fcrdns": {"192.0.2.25": MX1, "2001:db8::25": MX1, "192.0.2.26": MX2},
            "spf": {"record": "v=spf1 mx include:_spf.mail.test -all", "lookups": 2, "void": 0},
            "dmarc": {
                "name": f"_dmarc.{D}",
                "record": "v=DMARC1; p=reject; rua=mailto:dmarc@example.test",
                "policy": "reject",
            },
            "mta_sts": {"mode": "enforce", "max_age": 604800, "mx": [MX1, MX2]},
            "checked_at": "2026-11-12T12:00:00Z",
        }
    }
    assert web.calls == [(_url(), {"accept": "text/plain"})]


def test_each_name_and_type_is_asked_once_from_the_first_resolver(world, web):
    _probe()

    assert {resolver for resolver, _, _ in world.asked} == {R1}
    assert sorted(world.names) == sorted(
        [
            (D, "MX"),
            (MX1, "A"),
            (MX1, "AAAA"),
            (MX2, "A"),
            (MX2, "AAAA"),
            (_rev("192.0.2.25"), "PTR"),
            (_rev("2001:db8::25"), "PTR"),
            (_rev("192.0.2.26"), "PTR"),
            (D, "TXT"),
            ("_spf.mail.test", "TXT"),
            (f"_dmarc.{D}", "TXT"),
            (f"_mta-sts.{D}", "TXT"),
            (f"_smtp._tls.{D}", "TXT"),
        ]
    )


def test_the_host_name_is_taken_in_lower_case_without_the_final_dot(world, web):
    result = _probe("Example.TEST.")

    assert (result.status, result.message) == ("ok", GOOD)
    assert world.asked[0] == (R1, D, "MX")


def test_without_resolvers_given_the_configured_ones_are_asked(world, web, monkeypatch):
    monkeypatch.setattr(maildns.config, "PUBLIC_RESOLVERS", ("203.0.113.53",))

    maildns.probe(D, {}, now=NOW)

    assert {resolver for resolver, _, _ in world.asked} == {"203.0.113.53"}


def test_a_silent_resolver_hands_on_to_the_next(world, web):
    world.silent = {R1}

    result = _probe()

    assert (result.status, result.message) == ("ok", GOOD)
    assert world.asked[:3] == [(R1, D, "MX"), (R2, D, "MX"), (R1, MX1, "A")]


def test_no_resolver_answering_is_unknown_and_unreached(world, web):
    world.silent = {R1, R2}

    result = _probe()

    assert (result.status, result.message, result.reached) == (
        "unknown",
        f"{D}: {resolve.RESOLVERS_UNREACHABLE_MESSAGE}",
        False,
    )
    assert world.asked == [(R1, D, "MX"), (R2, D, "MX")]
    assert web.calls == []


def test_a_part_whose_names_go_unanswered_is_named_and_the_rest_judged(world, web):
    world.silent_names = {f"_dmarc.{D}"}

    result = _probe()

    assert (result.status, result.reached) == ("unknown", True)
    assert result.message == (
        "DMARC: public resolvers unreachable; 2 MX; FCrDNS; SPF (2/10 lookups); "
        "MTA-STS enforce; TLS-RPT"
    )


def test_fcrdns_is_not_judged_when_the_mx_part_is_not(world, web):
    world.silent_names = {MX1}

    result = _probe()

    assert (result.status, result.reached) == ("unknown", True)
    assert result.message == (
        "MX: public resolvers unreachable; FCrDNS: public resolvers unreachable; "
        "SPF (2/10 lookups); DMARC p=reject; MTA-STS enforce; TLS-RPT"
    )
    assert not any(rdtype == "PTR" for _, rdtype in world.names)


def test_findings_come_before_the_parts_not_judged(world, web):
    world.records[(D, "TXT")] = ["site-verification=abc"]
    world.silent_names = {f"_dmarc.{D}"}

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "no SPF record; DMARC: public resolvers unreachable",
    )


def test_a_domain_the_resolvers_do_not_know_is_unknown(world, web):
    result = _probe("nowhere.test")

    assert (result.status, result.message, result.reached) == (
        "unknown",
        "nowhere.test is unknown to the public resolvers",
        True,
    )
    assert world.names == [("nowhere.test", "MX")]


def test_a_name_dns_cannot_carry_is_not_asked(world, web):
    result = _probe("a" * 64 + ".test")

    assert result.status == "unknown"
    assert result.message.endswith(" is unknown to the public resolvers")
    assert world.asked == []


def test_the_lookup_budget_leaves_the_remaining_parts_unjudged(world, web, monkeypatch):
    monkeypatch.setattr(maildns, "MAX_LOOKUPS", 3)

    result = _probe()

    spent = "more than 3 lookups or 45 s"
    assert (result.status, result.reached) == ("unknown", True)
    assert result.message == "; ".join(
        f"{part}: {spent}" for part in ("MX", "FCrDNS", "SPF", "DMARC", "MTA-STS", "TLS-RPT")
    )
    assert len(world.asked) == 3
    assert web.calls == []


def test_a_spent_deadline_asks_nothing(world, web, monkeypatch):
    monkeypatch.setattr(maildns, "DEADLINE_S", 0)

    result = _probe()

    assert (result.status, result.message, result.reached) == (
        "unknown",
        f"{D}: more than 150 lookups or 0 s",
        False,
    )
    assert world.asked == []


# --- MX ------------------------------------------------------------------------------


def test_a_null_mx_is_a_hint_and_no_mail_host_is_asked(world, web):
    world.records = {
        (D, "MX"): [(0, "")],
        (D, "TXT"): ["v=spf1 -all"],
        (f"_dmarc.{D}", "TXT"): ["v=DMARC1; p=reject"],
    }

    result = _probe()

    assert (result.status, result.message) == (
        "ok",
        "SPF (0/10 lookups); DMARC p=reject; null MX: example.test receives no mail",
    )
    assert result.details["mail_dns"]["mx"] == [{"preference": 0, "host": "."}]
    assert not [n for n in world.names if n[1] in ("A", "AAAA", "PTR")]


def test_a_null_mx_next_to_other_mx_records_is_a_warning(world, web):
    world.records[(D, "MX")] = [(0, ""), (10, MX1)]

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "a null MX next to other MX records (RFC 7505 §3)",
    )


def test_without_mx_the_address_of_the_domain_takes_the_mail(world, web):
    del world.records[(D, "MX")]
    del world.records[(f"_mta-sts.{D}", "TXT")]
    world.records[(D, "A")] = ["192.0.2.30"]
    world.records[(_rev("192.0.2.30"), "PTR")] = [D]

    result = _probe()

    assert (result.status, result.message) == (
        "ok",
        "1 MX; FCrDNS; SPF (2/10 lookups); DMARC p=reject; TLS-RPT; "
        "no MX record, mail goes to the address of example.test",
    )
    assert result.details["mail_dns"]["mx"] == []
    assert result.details["mail_dns"]["spf"]["void"] == 1


def test_without_mx_and_address_senders_retry_for_days(world, web):
    del world.records[(D, "MX")]
    del world.records[(f"_mta-sts.{D}", "TXT")]

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "example.test has no MX record and no address: without a null MX (RFC 7505) "
        "senders retry for days",
    )


def test_an_mx_host_without_address_is_a_warning(world, web):
    del world.records[(MX2, "A")]

    result = _probe()

    assert (result.status, result.message) == ("warning", f"MX {MX2} has no address")


def test_mx_hosts_without_a_global_address_are_critical_and_not_reverse_checked(world, web):
    world.records[(MX1, "A")] = ["198.51.100.25"]
    del world.records[(MX1, "AAAA")]
    world.records[(MX2, "A")] = ["198.51.100.26"]

    result = _probe()

    assert (result.status, result.message) == (
        "critical",
        "no MX host of example.test has a global address: no mail arrives; "
        f"MX {MX1} has no global address; MX {MX2} has no global address",
    )
    assert "fcrdns" not in result.details["mail_dns"]
    assert not [n for n in world.names if n[1] == "PTR"]


def test_only_the_first_ten_mx_hosts_are_checked(world, web):
    hosts = [f"mx{i}.example.test" for i in range(1, 13)]
    world.records[(D, "MX")] = [(i * 10, h) for i, h in enumerate(hosts, 1)]
    # "mx" in SPF would meet more than ten MX records; that is a test of its own.
    world.records[(D, "TXT")] = ["v=spf1 include:_spf.mail.test -all"]
    for i, host in enumerate(hosts, 1):
        world.records[(host, "A")] = [f"192.0.2.{100 + i}"]
        world.records[(_rev(f"192.0.2.{100 + i}"), "PTR")] = [host]
    web.pages[_url()] = _page(_policy(mx=("*.example.test",)))

    result = _probe()

    assert (result.status, result.message) == (
        "ok",
        "10 MX; FCrDNS; SPF (1/10 lookups); DMARC p=reject; MTA-STS enforce; TLS-RPT; "
        "12 MX hosts, the first 10 checked",
    )
    assert len(result.details["mail_dns"]["mx"]) == 10
    assert not [n for n in world.names if n[0] in ("mx11.example.test", "mx12.example.test")]


# --- FCrDNS ------------------------------------------------------------------------


def test_an_address_without_ptr_is_a_warning(world, web):
    del world.records[(_rev("192.0.2.26"), "PTR")]

    result = _probe()

    assert (result.status, result.message) == ("warning", "192.0.2.26 has no PTR record")
    assert result.details["mail_dns"]["fcrdns"]["192.0.2.26"] == ""


def test_a_ptr_name_must_resolve_back_in_the_family_of_the_address(world, web):
    # mx2 has an A record only: the IPv6 address does not come back.
    world.records[(_rev("2001:db8::25"), "PTR")] = [MX2]

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        f"2001:db8::25: PTR {MX2} does not resolve back to it",
    )
    assert (MX2, "AAAA") in world.names


def test_at_most_ten_addresses_are_kept_and_reverse_checked(world, web):
    addresses = [f"192.0.2.{100 + i}" for i in range(1, 13)]
    world.records[(D, "MX")] = [(10, MX1)]
    world.records[(MX1, "A")] = addresses
    del world.records[(MX1, "AAAA")]
    world.records.update({(_rev(a), "PTR"): [MX1] for a in addresses})

    result = _probe()

    assert (result.status, result.message) == (
        "ok",
        "1 MX; FCrDNS; SPF (2/10 lookups); DMARC p=reject; MTA-STS enforce; TLS-RPT",
    )
    details = result.details["mail_dns"]
    assert details["mx_addresses"] == {MX1: addresses[:10]}
    assert list(details["fcrdns"]) == addresses[:10]
    assert [n for n, t in world.names if t == "PTR"] == [_rev(a) for a in addresses[:10]]


def test_at_most_three_ptr_names_are_resolved_back(world, web):
    names = ["p1.example.test", "p2.example.test", "p3.example.test", MX2]
    world.records[(_rev("192.0.2.26"), "PTR")] = names

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "192.0.2.26: PTR p1.example.test does not resolve back to it",
    )
    assert ("p3.example.test", "A") in world.names


def test_one_ptr_name_resolving_back_is_enough(world, web):
    world.records[(_rev("192.0.2.26"), "PTR")] = ["other.test", MX2]

    result = _probe()

    assert (result.status, result.message) == ("ok", GOOD)
    assert result.details["mail_dns"]["fcrdns"]["192.0.2.26"] == "other.test"


# --- SPF ---------------------------------------------------------------------------


def _with_spf(world, record, **records):
    world.records[(D, "TXT")] = [record]
    world.records.update({(name, "TXT"): [text] for name, text in records.items()})
    return _probe()


def test_no_spf_record_is_a_warning(world, web):
    world.records[(D, "TXT")] = ["v=spf10 -all", "site-verification=abc"]

    result = _probe()

    assert (result.status, result.message) == ("warning", "no SPF record")
    assert "spf" not in result.details["mail_dns"]


def test_two_spf_records_are_critical(world, web):
    world.records[(D, "TXT")] = ["v=spf1 -all", "V=SPF1 mx -all"]

    result = _probe()

    assert (result.status, result.message) == (
        "critical",
        "2 SPF records: receivers return permerror",
    )


@pytest.mark.parametrize(("depth", "status"), [(10, "ok"), (11, "critical")])
def test_more_than_ten_lookups_over_all_includes_are_critical(world, web, depth, status):
    chain = {f"s{i}.mail.test": f"v=spf1 include:s{i + 1}.mail.test -all" for i in range(1, depth)}
    chain[f"s{depth}.mail.test"] = "v=spf1 ip4:192.0.2.1 -all"
    world.records.update({(name, "TXT"): [text] for name, text in chain.items()})

    result = _with_spf(world, "v=spf1 include:s1.mail.test -all")

    assert result.status == status
    assert result.details["mail_dns"]["spf"]["lookups"] == depth
    if status == "ok":
        assert result.message == GOOD.replace("SPF (2/10", "SPF (10/10")
    else:
        assert result.message == "SPF: more than 10 DNS lookups (RFC 7208 §4.6.4)"
        assert ("s11.mail.test", "TXT") not in world.names


@pytest.mark.parametrize(
    ("record", "records", "status"),
    [
        ("v=spf1 a:v1.example.test a:v2.example.test -all", {}, "ok"),
        ("v=spf1 a:v1.example.test a:v2.example.test a:v3.example.test -all", {}, "critical"),
        # An IPv6 sender meets three void lookups at hosts with A records only.
        (
            "v=spf1 a:h1.example.test a:h2.example.test a:h3.example.test -all",
            {(f"h{i}.example.test", "A"): ["192.0.2.1"] for i in (1, 2, 3)},
            "critical",
        ),
        (
            "v=spf1 a:h1.example.test a:h2.example.test a:h3.example.test -all",
            {
                ("h1.example.test", "A"): ["192.0.2.1"],
                ("h2.example.test", "A"): ["192.0.2.1"],
                ("h3.example.test", "AAAA"): ["2001:db8::1"],
            },
            "ok",
        ),
        ("v=spf1 exists:e1.mail.test exists:e2.mail.test exists:e3.mail.test -all", {}, "critical"),
        ("v=spf1 mx:m1.mail.test mx:m2.mail.test mx:m3.mail.test -all", {}, "critical"),
    ],
)
def test_more_than_two_void_lookups_are_critical(world, web, record, records, status):
    world.records.update(records)

    result = _with_spf(world, record)

    assert result.status == status
    if status == "critical":
        assert result.message == "SPF: more than 2 void lookups (RFC 7208 §4.6.4)"


def test_exists_asks_for_an_a_record_only(world, web):
    _with_spf(world, "v=spf1 exists:e1.mail.test -all")

    assert ("e1.mail.test", "A") in world.names
    assert ("e1.mail.test", "AAAA") not in world.names


def test_a_without_domain_is_the_domain_of_the_record_holding_it(world, web):
    result = _with_spf(
        world, "v=spf1 include:_spf.mail.test -all", **{"_spf.mail.test": "v=spf1 a -all"}
    )

    assert result.status == "ok"
    assert ("_spf.mail.test", "A") in world.names
    assert result.details["mail_dns"]["spf"] == {
        "record": "v=spf1 include:_spf.mail.test -all",
        "lookups": 2,
        "void": 1,
    }


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ("v=spf1 include:none.mail.test -all", "include:none.mail.test has no SPF record"),
        ("v=spf1 redirect=none.mail.test", "redirect=none.mail.test has no SPF record"),
        ("v=spf1 include:two.mail.test -all", "include:two.mail.test has 2 SPF records"),
    ],
)
def test_an_include_or_redirect_target_needs_exactly_one_record(world, web, record, message):
    world.records[("none.mail.test", "TXT")] = ["site-verification=abc"]
    world.records[("two.mail.test", "TXT")] = ["v=spf1 -all", "v=spf1 +all"]

    result = _with_spf(world, record)

    assert (result.status, result.message) == ("critical", f"SPF: {message}")


def test_redirect_is_ignored_next_to_all(world, web):
    result = _with_spf(world, "v=spf1 redirect=_spf.mail.test -all")

    assert result.details["mail_dns"]["spf"]["lookups"] == 0
    assert ("_spf.mail.test", "TXT") not in world.names


@pytest.mark.parametrize(
    "record",
    [
        "v=spf1 -all include:none.mail.test",
        "v=spf1 ?all a:v1.example.test a:v2.example.test a:v3.example.test",
    ],
)
def test_terms_after_all_are_ignored(world, web, record):
    world.records[("none.mail.test", "TXT")] = ["site-verification=abc"]

    result = _with_spf(world, record)

    assert (result.status, result.message) == ("ok", GOOD.replace("SPF (2/10", "SPF (0/10"))
    assert result.details["mail_dns"]["spf"]["lookups"] == 0
    assert ("none.mail.test", "TXT") not in world.names
    assert ("v1.example.test", "A") not in world.names


def test_terms_after_all_are_still_parsed(world, web):
    result = _with_spf(world, "v=spf1 -all foo:bar")

    assert (result.status, result.message) == ("critical", "SPF: unknown mechanism 'foo:bar'")


def test_redirect_without_all_is_followed(world, web):
    result = _with_spf(world, "v=spf1 ip4:192.0.2.1 redirect=_spf.mail.test")

    assert result.status == "ok"
    assert result.details["mail_dns"]["spf"]["lookups"] == 1
    assert ("_spf.mail.test", "TXT") in world.names


def test_terms_with_macros_are_counted_but_not_followed(world, web):
    result = _with_spf(
        world,
        "v=spf1 exists:%{i}.spf.mail.test include:%{d1r}.mail.test redirect=%{d}.mail.test",
    )

    assert result.status == "ok"
    assert result.details["mail_dns"]["spf"]["lookups"] == 3
    assert not [name for name, _ in world.names if "%" in name]


def test_mx_with_more_than_ten_mx_records_is_critical(world, web):
    world.records[("big.mail.test", "MX")] = [(i, f"m{i}.mail.test") for i in range(11)]

    result = _with_spf(world, "v=spf1 mx:big.mail.test -all")

    assert (result.status, result.message) == (
        "critical",
        "SPF: mx:big.mail.test has more than 10 MX records",
    )


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ("v=spf1 foo -all", "unknown mechanism 'foo'"),
        ("v=spf1 +-all", "syntax error at '+-all'"),
        ("v=spf1 all:x", "syntax error at 'all:x'"),
        ("v=spf1 ip4:300.1.1.1 -all", "invalid address at 'ip4:300.1.1.1'"),
        ("v=spf1 ip4:2001:db8::1 -all", "invalid address at 'ip4:2001:db8::1'"),
        ("v=spf1 ip4 -all", "invalid address at 'ip4'"),
        ("v=spf1 ip4:192.0.2.0/33 -all", "prefix length out of range at 'ip4:192.0.2.0/33'"),
        ("v=spf1 ip6:2001:db8::/129 -all", "prefix length out of range at 'ip6:2001:db8::/129'"),
        ("v=spf1 ip6:fe80::1%eth0 -all", "invalid address at 'ip6:fe80::1%eth0'"),
        ("v=spf1 ip4:192.0.2.0/024 -all", "invalid prefix length at 'ip4:192.0.2.0/024'"),
        ("v=spf1 a/33 -all", "prefix length out of range at 'a/33'"),
        ("v=spf1 a//129 -all", "prefix length out of range at 'a//129'"),
        ("v=spf1 a.example.test -all", "unknown mechanism 'a.example.test'"),
        ("v=spf1 include -all", "include without a domain"),
        ("v=spf1 exists -all", "exists without a domain"),
        ("v=spf1 include: -all", "invalid domain at 'include:'"),
        ("v=spf1 include:%{c}.mail.test -all", "invalid domain at 'include:%{c}.mail.test'"),
        ("v=spf1 include:example.123 -all", "invalid domain at 'include:example.123'"),
        ("v=spf1 include:example -all", "invalid domain at 'include:example'"),
        ("v=spf1 include:a..example.test -all", "invalid domain at 'include:a..example.test'"),
        ("v=spf1 include:-x.test- -all", "invalid domain at 'include:-x.test-'"),
        ("v=spf1 exp=%{z} -all", "invalid domain at 'exp=%{z}'"),
        ("v=spf1 foo=%{z} -all", "syntax error at 'foo=%{z}'"),
        ("v=spf1 redirect=a.mail.test redirect=b.mail.test", "redirect= more than once"),
        ("v=spf1 exp=a.mail.test exp=b.mail.test -all", "exp= more than once"),
    ],
)
def test_a_record_receivers_cannot_parse_is_critical(world, web, record, message):
    result = _with_spf(world, record)

    assert (result.status, result.message) == ("critical", f"SPF: {message}")


@pytest.mark.parametrize(
    ("record", "lookups"),
    [
        ("v=spf1 a:mx1.example.test/24//64 -all", 1),
        ("v=spf1 mx/24 -all", 1),
        ("v=spf1  ip4:192.0.2.0/24  -all", 0),
        ("v=spf1 exists:%{i}.%{l1r+-}.spf.mail.test -all", 1),
        ("v=spf1 exp=%{c}.explain.mail.test -all", 0),
        ("v=spf1 foo=bar -all", 0),
        ("v=spf1 a:%%{c}.example.test -all", 1),
        ("v=spf1 include:_spf.mail.test. -all", 1),
        ("V=SPF1 IP4:192.0.2.1 INCLUDE:_SPF.MAIL.TEST ~ALL", 1),
        ("v=spf1", 0),
    ],
)
def test_records_receivers_parse(world, web, record, lookups):
    result = _with_spf(world, record)

    assert (result.status, result.message) == (
        "ok",
        GOOD.replace("SPF (2/10", f"SPF ({lookups}/10"),
    )


# --- DMARC -------------------------------------------------------------------------


def test_no_dmarc_record_is_a_warning(world, web):
    del world.records[(f"_dmarc.{D}", "TXT")]

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "no DMARC record: receivers apply no DMARC policy",
    )
    assert ("_dmarc.test", "TXT") in world.names


@pytest.mark.parametrize(
    "record",
    ["v=DMARC1; p=none; rua=mailto:d@example.test", "v=DMARC1; rua=mailto:d@example.test"],
)
def test_p_none_or_no_p_is_a_hint(world, web, record):
    world.records[(f"_dmarc.{D}", "TXT")] = [record]

    result = _probe()

    assert (result.status, result.message) == (
        "ok",
        "2 MX; FCrDNS; SPF (2/10 lookups); MTA-STS enforce; TLS-RPT; "
        "DMARC p=none: receivers take no action",
    )
    assert result.details["mail_dns"]["dmarc"]["policy"] == "none"


def test_two_dmarc_records_count_as_none(world, web):
    world.records[(f"_dmarc.{D}", "TXT")] = ["v=DMARC1; p=reject", "v=DMARC1; p=none"]

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "2 DMARC records at _dmarc.example.test: all are ignored; "
        "no DMARC record: receivers apply no DMARC policy",
    )


def test_an_invalid_policy_with_rua_acts_as_p_none(world, web):
    world.records[(f"_dmarc.{D}", "TXT")] = ["v=DMARC1; p=block; rua=mailto:d@example.test"]

    result = _probe()

    assert result.status == "ok"
    assert result.message.endswith(
        "_dmarc.example.test: invalid p, sp or np tag, receivers act as with p=none; "
        "DMARC p=none: receivers take no action"
    )


def test_an_invalid_policy_without_rua_is_not_applied(world, web):
    world.records[(f"_dmarc.{D}", "TXT")] = ["v=DMARC1; p=reject; sp=block"]

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "_dmarc.example.test: invalid p, sp or np tag and no rua: DMARC is not applied",
    )


def _subdomain(world, web, domain, dmarc):
    world.records = base(domain)
    del world.records[(f"_dmarc.{domain}", "TXT")]
    world.records.update({(f"_dmarc.{name}", "TXT"): [text] for name, text in dmarc.items()})
    web.pages[_url(domain)] = _page(_policy())
    result = _probe(domain)
    assert result.status == "ok"
    return result


@pytest.mark.parametrize(
    ("record", "good"),
    [
        ("v=DMARC1; p=reject; sp=quarantine", "DMARC sp=quarantine from example.test"),
        ("v=DMARC1; p=reject", "DMARC p=reject from example.test"),
    ],
)
def test_a_subdomain_takes_the_record_above_with_its_sp(world, web, record, good):
    result = _subdomain(world, web, "mail.example.test", {D: record})

    assert good in result.message.split("; ")
    assert result.details["mail_dns"]["dmarc"]["name"] == f"_dmarc.{D}"


def test_psd_y_points_to_the_organizational_domain_below(world, web):
    result = _subdomain(
        world,
        web,
        "mail.shop.example.test",
        {"shop.example.test": "v=DMARC1; p=quarantine", D: "v=DMARC1; p=reject; psd=y"},
    )

    assert "DMARC p=quarantine from shop.example.test" in result.message.split("; ")


def test_psd_y_without_a_record_below_applies_its_own(world, web):
    result = _subdomain(world, web, "mail.shop.example.test", {D: "v=DMARC1; p=reject; psd=y"})

    assert "DMARC p=reject from example.test" in result.message.split("; ")


def test_psd_n_ends_the_walk(world, web):
    result = _subdomain(
        world,
        web,
        "mail.shop.example.test",
        {"shop.example.test": "v=DMARC1; p=quarantine; psd=n", D: "v=DMARC1; p=reject"},
    )

    assert "DMARC p=quarantine from shop.example.test" in result.message.split("; ")
    assert ("_dmarc.example.test", "TXT") not in world.names


def test_the_walk_asks_at_most_eight_names(world, web):
    domain = "a.b.c.d.e.f.g.h.example.test"
    world.records = base(domain)
    del world.records[(f"_dmarc.{domain}", "TXT")]
    web.pages[_url(domain)] = _page(_policy())

    _probe(domain)

    asked = [name for name, rdtype in world.names if name.startswith("_dmarc.")]
    assert asked == [
        f"_dmarc.{domain}",
        "_dmarc.d.e.f.g.h.example.test",
        "_dmarc.e.f.g.h.example.test",
        "_dmarc.f.g.h.example.test",
        "_dmarc.g.h.example.test",
        "_dmarc.h.example.test",
        "_dmarc.example.test",
        "_dmarc.test",
    ]


# --- MTA-STS -------------------------------------------------------------------------


def test_without_mta_sts_record_no_policy_is_fetched(world, web):
    world.records[(f"_mta-sts.{D}", "TXT")] = ["v=STSv2; id=1", "v=STSv1 ; id=1"]

    result = _probe()

    assert (result.status, result.message) == ("ok", GOOD.replace("; MTA-STS enforce", ""))
    assert web.calls == []


@pytest.mark.parametrize(
    "record",
    [
        "v=STSv1;",
        "v=STSv1; id=",
        "v=STSv1; id=abc-def",
        "v=STSv1; id=" + "a" * 33,
        "v=STSv1; id=1;;",
        "v=STSv1; ext=1",
        "v=STSv1; id=1; e x=1",
    ],
)
def test_an_invalid_mta_sts_record_is_a_warning(world, web, record):
    world.records[(f"_mta-sts.{D}", "TXT")] = [record]

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "MTA-STS record invalid: senders ignore MTA-STS",
    )
    assert web.calls == []


@pytest.mark.parametrize(
    "record", ["v=STSv1;id=1", "v=STSv1; id=1;", "v=STSv1;\tid=1 ; ext.x=y", "v=STSv1; id=1 "]
)
def test_valid_mta_sts_records(world, web, record):
    world.records[(f"_mta-sts.{D}", "TXT")] = [record]

    assert (_probe().status, len(web.calls)) == ("ok", 1)


def test_two_mta_sts_records_are_a_warning(world, web):
    world.records[(f"_mta-sts.{D}", "TXT")] = ["v=STSv1; id=1", "v=STSv1; id=2"]

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "2 MTA-STS records: senders ignore MTA-STS",
    )


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (FetchError("connection refused"), "MTA-STS policy not retrievable: connection refused"),
        (FetchError("bad\x00thing"), "MTA-STS policy not retrievable: bad?thing"),
        (_page(b"", "text/html", 404), "MTA-STS policy: HTTP 404"),
        (_page(_policy(), "text/html"), "MTA-STS policy served as text/html, not text/plain"),
        (_page(_policy(), ""), "MTA-STS policy served as no type, not text/plain"),
    ],
)
def test_a_policy_not_served_right_is_a_warning(world, web, answer, message):
    web.pages[_url()] = answer

    result = _probe()

    assert (result.status, result.message) == ("warning", message)


def test_the_media_type_is_compared_without_case_and_parameters(world, web):
    web.pages[_url()] = _page(_policy(), "Text/Plain ; charset=UTF-8")

    assert (_probe().status, _probe().message) == ("ok", GOOD)


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (b"\xff", "not UTF-8"),
        (b"version: STSv1\nmode enforce\n", "line 2"),
        (b"version: STSv1\nmode:\n", "line 2"),
        (b"version: STSv1\nmo de: enforce\n", "line 2"),
        (b"version: STSv1\nmode: enf\x00orce\n", "line 2"),
        (_policy().replace(b"STSv1", b"STSv2"), "version is not STSv1"),
        (_policy(mode="enforcing"), "mode is not enforce, testing or none"),
        (_policy(max_age="-1"), "max_age is no number up to 31557600"),
        (_policy(max_age="31557601"), "max_age is no number up to 31557600"),
        (_policy(max_age="1e5"), "max_age is no number up to 31557600"),
        (_policy().replace(b"max_age: 604800\r\n", b""), "max_age is no number up to 31557600"),
        (_policy(mx=()), "no mx line"),
        (_policy(mx=("mx1.example.test:25",)), "an mx line is no host name"),
        (_policy(mx=("*.*.example.test",)), "an mx line is no host name"),
        (_policy(mx=("mx_1.example.test",)), "an mx line is no host name"),
        (_policy(mx=("-mx.example.test",)), "an mx line is no host name"),
    ],
)
def test_an_invalid_policy_is_a_warning(world, web, body, error):
    web.pages[_url()] = _page(body)

    result = _probe()

    assert (result.status, result.message) == ("warning", f"MTA-STS policy invalid: {error}")


def test_a_policy_may_use_lf_blank_lines_tabs_and_other_fields(world, web):
    body = b"version: STSv1\n\nmode:\tenforce\nmx: MX1.Example.TEST.\nmx: *.example.test\n"
    web.pages[_url()] = _page(body + b"max_age: 31557600\nfuture_field: x\n")

    result = _probe()

    assert (result.status, result.message) == ("ok", GOOD)
    assert result.details["mail_dns"]["mta_sts"] == {
        "mode": "enforce",
        "max_age": 31557600,
        "mx": [MX1, "*.example.test"],
    }


def test_the_details_keep_ten_policy_patterns_and_the_count(world, web):
    patterns = [f"mx{n}.example.test" for n in range(3, 3000)]
    web.pages[_url()] = _page(_policy(mx=(MX1, MX2, *patterns)))

    result = _probe()

    assert (result.status, result.message) == ("ok", GOOD)
    sts = result.details["mail_dns"]["mta_sts"]
    assert sts["mx"] == [MX1, MX2, *patterns[:8]]
    assert sts["mx_count"] == 2999


@pytest.mark.parametrize(
    ("mode", "status", "message"),
    [
        ("enforce", "critical", f"MX {MX2} is not in the MTA-STS policy: senders refuse it"),
        ("testing", "warning", f"MX {MX2} is not in the MTA-STS policy (mode testing)"),
    ],
)
def test_an_mx_host_the_policy_does_not_name(world, web, mode, status, message):
    web.pages[_url()] = _page(_policy(mode=mode, mx=(MX1,)))

    result = _probe()

    assert (result.status, result.message) == (status, message)


def test_mode_none_is_a_hint_and_needs_no_mx_line(world, web):
    web.pages[_url()] = _page(_policy(mode="none", mx=()))

    result = _probe()

    assert (result.status, result.message) == (
        "ok",
        "2 MX; FCrDNS; SPF (2/10 lookups); DMARC p=reject; TLS-RPT; MTA-STS mode none",
    )


def test_the_first_of_two_mode_fields_counts(world, web):
    body = _policy(mode="testing", mx=(MX1,), extra=("mode: enforce",))
    web.pages[_url()] = _page(body)

    result = _probe()

    assert result.status == "warning"
    assert result.details["mail_dns"]["mta_sts"]["mode"] == "testing"


@pytest.mark.parametrize(
    ("pattern", "host", "match"),
    [
        (MX1, MX1, True),
        (MX1, MX2, False),
        ("*.example.test", MX1, True),
        ("*.example.test", "a.mx1.example.test", False),
        ("*.example.test", "example.test", False),
        ("*.example.test", ".example.test", False),
        ("*.example.test", "mx1.example.testx", False),
    ],
)
def test_a_wildcard_stands_for_the_left_most_label_only(pattern, host, match):
    assert maildns._sts_match(pattern, host) is match


# --- TLS-RPT -----------------------------------------------------------------------


def test_mta_sts_without_tls_rpt_is_a_hint(world, web):
    del world.records[(f"_smtp._tls.{D}", "TXT")]

    result = _probe()

    assert (result.status, result.message) == (
        "ok",
        "2 MX; FCrDNS; SPF (2/10 lookups); DMARC p=reject; MTA-STS enforce; "
        "MTA-STS without TLS-RPT: no reports of failed deliveries",
    )


def test_no_tls_rpt_without_mta_sts_is_nothing(world, web):
    del world.records[(f"_smtp._tls.{D}", "TXT")]
    del world.records[(f"_mta-sts.{D}", "TXT")]

    result = _probe()

    assert (result.status, result.message) == (
        "ok",
        "2 MX; FCrDNS; SPF (2/10 lookups); DMARC p=reject",
    )


@pytest.mark.parametrize(
    "record",
    [
        "v=TLSRPTv1; rua=ftp://r.example.test/",
        "v=TLSRPTv1; x=y",
        "v=TLSRPTv1; rua=",
        "v=TLSRPTv1; rua=mailto:a@example.test,",
        "v=TLSRPTv1; rua=mailto:a b@example.test",
        # RFC 8460 §3: an exclamation point in a URI must be encoded.
        "v=TLSRPTv1; rua=mailto:a!b@example.test",
    ],
)
def test_an_invalid_tls_rpt_record_is_a_warning(world, web, record):
    world.records[(f"_smtp._tls.{D}", "TXT")] = [record]

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "TLS-RPT record invalid: reporters ignore it",
    )


@pytest.mark.parametrize(
    "record",
    [
        "v=TLSRPTv1;rua=mailto:a@example.test",
        "v=TLSRPTv1; rua=mailto:a@example.test,https://r.example.test/tlsrpt",
        "v=TLSRPTv1; rua=MAILTO:a@example.test , mailto:b@example.test;",
        "v=TLSRPTv1; rua=https://r.example.test/?a=b&c=d; ext=1",
    ],
)
def test_valid_tls_rpt_records(world, web, record):
    world.records[(f"_smtp._tls.{D}", "TXT")] = [record]

    assert (_probe().status, _probe().message) == ("ok", GOOD)


def test_two_tls_rpt_records_are_a_warning(world, web):
    world.records[(f"_smtp._tls.{D}", "TXT")] = [
        "v=TLSRPTv1; rua=mailto:a@example.test",
        "v=TLSRPTv1; rua=mailto:b@example.test",
    ]

    result = _probe()

    assert (result.status, result.message) == (
        "warning",
        "2 TLS-RPT records: reporters ignore TLS-RPT",
    )


# --- text from DNS and HTTP ------------------------------------------------------------


def test_control_characters_never_reach_the_message(world, web):
    result = _with_spf(world, "v=spf1 fo\x00o -all")

    assert (result.status, result.message) == ("critical", "SPF: unknown mechanism 'fo?o'")
    assert result.details["mail_dns"]["spf"]["record"] == "v=spf1 fo?o -all"


def test_records_in_the_details_are_bounded(world, web):
    world.records[(f"_dmarc.{D}", "TXT")] = ["v=DMARC1; p=reject; rua=mailto:" + "d" * 900]

    result = _with_spf(world, "v=spf1 " + "ip4:192.0.2.1 " * 100 + "-all")

    assert result.status == "ok"
    details = result.details["mail_dns"]
    assert len(details["spf"]["record"]) == maildns.MAX_RECORD
    assert len(details["dmarc"]["record"]) == maildns.MAX_RECORD


LONG = 200_000


@pytest.mark.parametrize(
    ("name", "text"),
    [
        (D, "v=spf1 " + "ip4:192.0.2.1 " * (LONG // 14) + "-all"),
        (D, "v=spf1 exists:" + "%{d}" * (LONG // 4) + ".mail.test -all"),
        (D, "v=spf1 " + "a" * LONG),
        (D, "v=spf1 a:" + "a." * (LONG // 2) + "test -all"),
        (D, "v=spf1 a" + "/1" * (LONG // 2)),
        (D, "v=spf1 x=" + "%" * LONG),
        (f"_dmarc.{D}", "v=DMARC1; p=x; rua=" + "a," * (LONG // 2)),
        (f"_dmarc.{D}", "v=DMARC1; p=x; rua=!" + "1" * LONG + "x"),
        (f"_dmarc.{D}", "v=DMARC1; " + "p" * LONG),
        (f"_mta-sts.{D}", "v=STSv1; " + "id=1; " * (LONG // 6)),
        (f"_mta-sts.{D}", "v=STSv1; id=1; " + "a" * LONG),
        (f"_smtp._tls.{D}", "v=TLSRPTv1; rua=" + "mailto:a@example.test," * (LONG // 22) + "x"),
        (f"_smtp._tls.{D}", "v=TLSRPTv1; rua=mailto:" + "a" * LONG + " x"),
    ],
)
def test_long_records_are_judged_in_linear_time(world, web, name, text):
    world.records[(name, "TXT")] = [text]

    started = time.perf_counter()
    _probe()

    assert time.perf_counter() - started < 5


def test_a_long_policy_is_judged_in_linear_time(world, web):
    lines = "".join(f"mx: m{i}.example.test\n" for i in range(LONG // 20))
    web.pages[_url()] = _page(_policy(mx=(MX1, MX2)) + lines.encode() + b"x" * LONG)

    started = time.perf_counter()
    result = _probe()

    assert time.perf_counter() - started < 5
    assert result.message.startswith("MTA-STS policy invalid: line ")


# --- query -------------------------------------------------------------------------


@pytest.fixture
def stub_resolve(monkeypatch):
    calls = []

    def install(outcome):
        def fake_resolve(self, qname, rdtype, **kwargs):
            calls.append((list(self.nameservers), self.lifetime, qname.to_text(), rdtype, kwargs))
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        monkeypatch.setattr(dns.resolver.Resolver, "resolve", fake_resolve)
        return calls

    return install


def _rrset(rdtype, *texts):
    return SimpleNamespace(rrset=dns.rrset.from_text("example.test.", 300, "IN", rdtype, *texts))


@pytest.mark.parametrize(
    ("rdtype", "answer", "values"),
    [
        ("TXT", _rrset("TXT", '"v=spf1 " "-all"'), ("v=spf1 -all",)),
        (
            "TXT",
            SimpleNamespace(rrset=[SimpleNamespace(strings=(b"v=spf1 ", b"\xc3\xa4"))]),
            ("v=spf1 ��",),
        ),
        ("MX", _rrset("MX", "10 MX1.Example.TEST."), ((10, MX1),)),
        ("MX", _rrset("MX", "0 ."), ((0, ""),)),
        ("PTR", _rrset("PTR", "Mx1.Example.Test."), (MX1,)),
        ("A", _rrset("A", "192.0.2.25"), ("192.0.2.25",)),
        ("AAAA", _rrset("AAAA", "2001:db8::25"), ("2001:db8::25",)),
    ],
)
def test_query_reads_the_records(stub_resolve, rdtype, answer, values):
    calls = stub_resolve(answer)

    assert maildns.query(R1, D, rdtype) == maildns.DnsAnswer(AnswerStatus.OK, values)
    assert calls == [
        (
            [R1],
            resolve.QUERY_LIFETIME_S,
            "example.test.",
            rdtype,
            {"raise_on_no_answer": False, "search": False},
        )
    ]


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        (SimpleNamespace(rrset=None), AnswerStatus.NODATA),
        (dns.resolver.NXDOMAIN(), AnswerStatus.NXDOMAIN),
        (dns.resolver.LifetimeTimeout(timeout=2.0, errors=[]), AnswerStatus.SILENT),
        (dns.resolver.NoNameservers(), AnswerStatus.SILENT),
        (OSError("network unreachable"), AnswerStatus.SILENT),
    ],
)
def test_query_tells_what_kind_of_no_answer(stub_resolve, outcome, status):
    stub_resolve(outcome)

    assert maildns.query(R1, D, "TXT") == maildns.DnsAnswer(status)
