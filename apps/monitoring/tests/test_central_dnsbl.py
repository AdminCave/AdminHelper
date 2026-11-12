# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensor dnsbl of central checks (R-1224): the domain's mail hosts on blocklists.

The public resolvers are a stand-in for maildns.query, the lists one for
dnsbl.list_query. 198.51.100.0/24 stands for addresses that are not global.
"""

import ipaddress
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import get_args

import dns.exception
import dns.resolver
import dns.rrset
import pytest

from app.central import dnsbl, maildns, resolve
from app.central.maildns import DnsAnswer
from app.central.resolve import AnswerStatus
from app.check_configs import DnsblList
from app.core import config
from app.core.time import iso_utc

NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
R1, R2 = "192.0.2.53", "198.51.100.53"
RESOLVERS = (R1, R2)
D = "example.test"
MX1, MX2 = "mx1.example.test", "mx2.example.test"
A1, A2 = "192.0.2.25", "192.0.2.26"
NOT_GLOBAL = ipaddress.ip_network("198.51.100.0/24")
KEY = "exampledqskey42"
FREE = "PSBL, SpamCop, UCEPROTECT level 1"
CLEAN = f"2 addresses not listed on {FREE}"
UNREACHABLE = resolve.RESOLVERS_UNREACHABLE_MESSAGE
ZONES = {name: blocklist.zone for name, blocklist in dnsbl.LISTS.items()}
ZONES["spamhaus_zen"] = f"{KEY}.zen.dq.spamhaus.net"


def _rev(address: str) -> str:
    return ".".join(reversed(address.split(".")))


def _q(address: str, name: str) -> str:
    return f"{_rev(address)}.{ZONES[name]}"


def _test_entry(name: str, last: int = 2) -> str:
    return f"{last}.0.0.127.{ZONES[name]}"


class World:
    """maildns.query stand-in: records by (name, type); a name with records of other
    types exists (NODATA), any other name does not (NXDOMAIN)."""

    def __init__(self, records):
        self.records = records
        self.silent: set[str] = set()
        self.silent_names: set[str] = set()
        self.asked: list[tuple[str, str, str]] = []

    def __call__(self, resolver, name, rdtype):
        self.asked.append((resolver, name, rdtype))
        if resolver in self.silent or name in self.silent_names:
            return DnsAnswer(AnswerStatus.SILENT)
        value = self.records.get((name, rdtype))
        if value is not None:
            return DnsAnswer(AnswerStatus.OK, tuple(value))
        if any(n == name for n, _ in self.records):
            return DnsAnswer(AnswerStatus.NODATA)
        return DnsAnswer(AnswerStatus.NXDOMAIN)


class Lists:
    """dnsbl.list_query stand-in: answers by (name, type). Every list lists its test
    entry 127.0.0.2; any other name has no record (NODATA, as the real lists answer)."""

    def __init__(self, clock=None):
        self.answers: dict[tuple[str, str], object] = {
            (_test_entry(name), "A"): ("127.0.0.2",) for name in ZONES
        }
        self.asked: list[tuple[str, str]] = []
        self.clock = clock

    def __call__(self, name, rdtype):
        self.asked.append((name, rdtype))
        if self.clock is not None:
            self.clock.now += 20.0
        value = self.answers.get((name, rdtype), AnswerStatus.NODATA)
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, AnswerStatus):
            return DnsAnswer(value)
        return DnsAnswer(AnswerStatus.OK, tuple(value))

    def put(self, address, name, codes=("127.0.0.2",), reason=None):
        self.answers[(_q(address, name), "A")] = codes
        if reason is not None:
            self.answers[(_q(address, name), "TXT")] = (reason,)

    def zone_asked(self, name) -> list[tuple[str, str]]:
        return [(n, t) for n, t in self.asked if n.endswith(f".{ZONES[name]}")]


def base() -> dict:
    """A domain with two mail hosts and two global IPv4 addresses."""
    return {
        (D, "MX"): [(10, MX1), (20, MX2)],
        (MX1, "A"): [A1],
        (MX2, "A"): [A2, "198.51.100.26"],
    }


@pytest.fixture(autouse=True)
def _global(monkeypatch):
    monkeypatch.setattr(
        dnsbl, "is_global_address", lambda ip: not (ip.version == 4 and ip in NOT_GLOBAL)
    )
    monkeypatch.setattr(config, "SPAMHAUS_DQS_KEY", "")


@pytest.fixture
def world(monkeypatch):
    stand_in = World(base())
    monkeypatch.setattr(maildns, "query", stand_in)
    return stand_in


@pytest.fixture
def lists(monkeypatch):
    stand_in = Lists()
    monkeypatch.setattr(dnsbl, "list_query", stand_in)
    return stand_in


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(config, "SPAMHAUS_DQS_KEY", KEY)


def _probe(params=None, host=D):
    return dnsbl.probe(host, params or {}, None, now=NOW, resolvers=RESOLVERS)


def _details(result) -> dict:
    return result.details["dnsbl"]


# --- the whole run ------------------------------------------------------------------


def test_clean_addresses_are_ok(world, lists):
    result = _probe()

    assert (result.status, result.message, result.reached) == ("ok", CLEAN, True)
    assert result.metrics == {"listed_count": 0}
    assert result.details == {
        "dnsbl": {
            "domain": D,
            "lists": ["psbl", "spamcop", "uceprotect1"],
            "mx": [MX1, MX2],
            "addresses": [A1, A2],
            "listed": [],
            "not_judged": [],
            "checked_at": iso_utc(NOW),
        }
    }
    # Only the IPv4 addresses of the mail hosts, over the first resolver that answers.
    assert world.asked == [(R1, D, "MX"), (R1, MX1, "A"), (R1, MX2, "A")]
    # Each list: the two test entries first, then the addresses; no TXT without a listing.
    assert lists.asked == [
        (q, "A")
        for name in ("psbl", "spamcop", "uceprotect1")
        for q in (_test_entry(name), _test_entry(name, 1), _q(A1, name), _q(A2, name))
    ]


def test_a_listing_warns_with_its_codes_and_the_list_s_reason(world, lists):
    reason = f"Blocked - see https://www.spamcop.net/bl.shtml?{A1}"
    lists.put(A1, "spamcop", reason=reason)

    result = _probe()

    assert (result.status, result.reached) == ("warning", True)
    assert result.message == f"{A1} listed on SpamCop (127.0.0.2)"
    assert result.metrics == {"listed_count": 1}
    assert _details(result)["listed"] == [
        {"address": A1, "list": "spamcop", "codes": ["127.0.0.2"], "reason": reason}
    ]
    assert lists.asked.count((_q(A1, "spamcop"), "TXT")) == 1


def test_listings_are_grouped_by_address_and_counted_per_list(world, lists):
    lists.put(A1, "psbl")
    lists.put(A1, "spamcop")
    lists.put(A2, "uceprotect1", codes=("127.0.0.4", "127.0.0.2"))

    result = _probe()

    assert result.status == "warning"
    assert result.message == (
        f"{A1} listed on PSBL (127.0.0.2), SpamCop (127.0.0.2); "
        f"{A2} listed on UCEPROTECT level 1 (127.0.0.2, 127.0.0.4)"
    )
    assert result.metrics == {"listed_count": 3}
    assert [(e["address"], e["list"], e["reason"]) for e in _details(result)["listed"]] == [
        (A1, "psbl", ""),
        (A1, "spamcop", ""),
        (A2, "uceprotect1", ""),
    ]


def test_a_listing_and_a_list_not_judged_both_reach_the_message(world, lists):
    lists.put(A1, "psbl")
    lists.answers[(_test_entry("spamcop"), "A")] = AnswerStatus.SILENT

    result = _probe()

    assert result.status == "warning"
    assert result.message == f"{A1} listed on PSBL (127.0.0.2); SpamCop not judged: no answer"
    assert result.metrics == {"listed_count": 1}
    assert _details(result)["not_judged"] == [{"list": "spamcop", "reason": "no answer"}]


def test_the_host_is_asked_in_lower_case_without_the_final_dot(world, lists):
    result = _probe(host="Example.TEST.")

    assert result.status == "ok"
    assert world.asked[0] == (R1, D, "MX")
    assert _details(result)["domain"] == D


# --- the lists of a run -------------------------------------------------------------


def test_the_config_literal_names_exactly_the_lists():
    assert set(get_args(DnsblList)) == set(dnsbl.LISTS)
    assert set(dnsbl.FREE_LISTS) == set(dnsbl.LISTS) - {"spamhaus_zen"}


@pytest.mark.parametrize("params", [{}, {"lists": None}])
def test_without_a_key_the_free_lists_are_asked(world, lists, params):
    result = _probe(params)

    assert _details(result)["lists"] == ["psbl", "spamcop", "uceprotect1"]
    assert result.message == CLEAN
    assert lists.zone_asked("spamhaus_zen") == []


def test_with_a_key_spamhaus_zen_is_asked_over_its_dqs_zone(world, lists, key):
    lists.put(A1, "spamhaus_zen", codes=("127.0.0.4",))

    result = _probe()

    assert _details(result)["lists"] == ["psbl", "spamcop", "uceprotect1", "spamhaus_zen"]
    assert result.status == "warning"
    assert result.message == f"{A1} listed on Spamhaus ZEN (127.0.0.4)"
    # Spamhaus names no reason over DQS; the listing stands without one.
    assert _details(result)["listed"] == [
        {"address": A1, "list": "spamhaus_zen", "codes": ["127.0.0.4"]}
    ]
    assert lists.zone_asked("spamhaus_zen") == [
        (_test_entry("spamhaus_zen"), "A"),
        (_test_entry("spamhaus_zen", 1), "A"),
        (_q(A1, "spamhaus_zen"), "A"),
        (_q(A2, "spamhaus_zen"), "A"),
    ]


def test_chosen_lists_are_the_only_ones_asked(world, lists):
    result = _probe({"lists": ["uceprotect1"]})

    assert result.message == "2 addresses not listed on UCEPROTECT level 1"
    assert {n for n, _ in lists.asked} == {
        _test_entry("uceprotect1"),
        _test_entry("uceprotect1", 1),
        _q(A1, "uceprotect1"),
        _q(A2, "uceprotect1"),
    }


def test_spamhaus_without_a_key_is_left_out_with_a_hint(world, lists):
    result = _probe({"lists": ["spamhaus_zen", "psbl"]})

    assert result.status == "ok"
    assert result.message == f"2 addresses not listed on PSBL; {dnsbl.NO_KEY_HINT}"
    assert _details(result)["lists"] == ["psbl"]
    assert lists.zone_asked("spamhaus_zen") == []


def test_only_spamhaus_without_a_key_asks_nothing(world, lists):
    result = _probe({"lists": ["spamhaus_zen"]})

    assert (result.status, result.message, result.reached) == ("unknown", dnsbl.NO_KEY_HINT, True)
    assert result.metrics == {}
    assert world.asked == [] and lists.asked == []


# --- answers a list is not judged by ------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "answer", "reason"),
    [
        (2, AnswerStatus.NODATA, "test entry 127.0.0.2 not listed (RFC 5782 §5)"),
        (2, AnswerStatus.NXDOMAIN, "test entry 127.0.0.2 not listed (RFC 5782 §5)"),
        (1, ("127.0.0.2",), "127.0.0.1 listed, which no list may (RFC 5782 §5)"),
        # A resolver that rewrites answers, or a list that answers with an address.
        (2, ("192.0.2.99",), "answer outside 127.0.0.0/8"),
        (2, ("127.255.255.254",), "error code 127.255.255.254"),
        (2, AnswerStatus.SILENT, "no answer"),
        (2, RuntimeError("resolver broke"), "no answer"),
    ],
)
def test_a_list_failing_its_test_entries_is_not_judged(world, lists, entry, answer, reason):
    lists.answers[(_test_entry("psbl", entry), "A")] = answer

    result = _probe()

    assert (result.status, result.reached) == ("unknown", True)
    assert result.message == (
        f"PSBL not judged: {reason}; 2 addresses not listed on SpamCop, UCEPROTECT level 1"
    )
    assert result.metrics == {}
    assert _details(result)["not_judged"] == [{"list": "psbl", "reason": reason}]
    assert (_q(A1, "psbl"), "A") not in lists.asked


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (("192.0.2.99",), "answer outside 127.0.0.0/8"),
        (("127.0.0.2", "192.0.2.99"), "answer outside 127.0.0.0/8"),
        (("127.255.255.252",), "error code 127.255.255.252"),
        (AnswerStatus.SILENT, "no answer"),
    ],
)
def test_an_odd_answer_for_an_address_leaves_the_list_not_judged(world, lists, answer, reason):
    lists.put(A1, "psbl")
    lists.answers[(_q(A2, "psbl"), "A")] = answer

    result = _probe()

    # A list that answers oddly in this run vouches for none of its answers in it.
    assert result.status == "unknown"
    assert result.message.startswith(f"PSBL not judged: {reason}; ")
    assert _details(result)["listed"] == []


def test_lists_that_all_fail_give_no_clean_part(world, lists):
    for name in ("psbl", "spamcop", "uceprotect1"):
        lists.answers[(_test_entry(name), "A")] = AnswerStatus.SILENT

    result = _probe()

    assert result.status == "unknown"
    assert result.message == (
        "PSBL not judged: no answer; SpamCop not judged: no answer; "
        "UCEPROTECT level 1 not judged: no answer"
    )


def test_the_reason_is_bounded_and_printable_and_may_be_missing(world, lists):
    lists.put(A1, "psbl", reason="a\x1bb" + "x" * 300)
    lists.put(A2, "psbl")
    lists.answers[(_q(A2, "psbl"), "TXT")] = AnswerStatus.SILENT

    result = _probe()

    assert [e["reason"] for e in _details(result)["listed"]] == ["a?b" + "x" * 197, ""]


# --- the DQS key ----------------------------------------------------------------------


def _key_scenario(lists, scenario):
    test_entry = (_test_entry("spamhaus_zen"), "A")
    address = (_q(A1, "spamhaus_zen"), "A")
    if scenario == "listed":
        lists.answers[address] = ("127.0.0.4",)
    elif scenario == "error code":
        lists.answers[address] = ("127.255.255.254",)
    elif scenario == "outside":
        lists.answers[test_entry] = ("192.0.2.99",)
    elif scenario == "silent":
        lists.answers[test_entry] = AnswerStatus.SILENT
    elif scenario == "raises":
        lists.answers[test_entry] = dns.exception.DNSException(f"no answer for {test_entry[0]}")
    elif scenario == "raises other":
        lists.answers[address] = RuntimeError(f"cannot ask {address[0]}")


@pytest.mark.parametrize(
    "scenario", ["clean", "listed", "error code", "outside", "silent", "raises", "raises other"]
)
def test_the_key_leaves_the_sensor_on_no_path(world, lists, key, caplog, scenario):
    _key_scenario(lists, scenario)

    with caplog.at_level(logging.DEBUG):
        result = _probe()

    assert any(KEY in name for name, _ in lists.asked)
    assert KEY not in repr(result)
    assert KEY not in caplog.text


# --- the mail hosts -------------------------------------------------------------------


def test_a_null_mx_asks_no_list(world, lists):
    world.records[(D, "MX")] = [(0, "")]

    result = _probe()

    assert (result.status, result.reached) == ("unknown", True)
    assert result.message == f"null MX: {D} receives no mail"
    assert _details(result)["mx"] == []
    assert lists.asked == []


def test_without_an_mx_record_the_domain_s_own_address_takes_mail(world, lists):
    world.records = {(D, "A"): ["192.0.2.80"], (D, "TXT"): ["v=spf1 -all"]}

    result = _probe()

    assert (result.status, result.message) == ("ok", f"1 address not listed on {FREE}")
    assert _details(result)["mx"] == [D]
    assert _details(result)["addresses"] == ["192.0.2.80"]


def test_a_domain_unknown_to_the_resolvers_asks_no_list(world, lists):
    world.records = {}

    result = _probe()

    # The resolvers answered: the run reached them, the domain just does not exist.
    assert (result.status, result.reached) == ("unknown", True)
    assert result.message == f"{D} is unknown to the public resolvers"
    assert lists.asked == []


def test_silent_resolvers_give_no_verdict(world, lists):
    world.silent = {R1, R2}

    result = _probe()

    assert (result.status, result.message, result.reached) == (
        "unknown",
        f"{D}: {UNREACHABLE}",
        False,
    )
    assert result.metrics == {}
    assert lists.asked == []


def test_the_second_resolver_answers_for_a_silent_first(world, lists):
    world.silent = {R1}

    result = _probe()

    assert result.message == CLEAN
    assert (R2, D, "MX") in world.asked


def test_a_mail_host_no_resolver_answers_for_is_a_gap(world, lists):
    world.silent_names = {MX2}

    result = _probe()

    assert (result.status, result.reached) == ("unknown", True)
    assert result.message == f"MX {MX2} not judged: {UNREACHABLE}; 1 address not listed on {FREE}"
    assert result.metrics == {}
    assert _details(result)["addresses"] == [A1]


def test_a_gap_does_not_hide_a_listing(world, lists):
    world.silent_names = {MX2}
    lists.put(A1, "psbl")

    result = _probe()

    assert result.status == "warning"
    assert result.message == f"{A1} listed on PSBL (127.0.0.2); MX {MX2} not judged: {UNREACHABLE}"


def test_mail_hosts_without_any_answer_ask_no_list(world, lists):
    world.silent_names = {MX1, MX2}

    result = _probe()

    assert (result.status, result.reached) == ("unknown", True)
    assert result.message == (
        f"MX {MX1} not judged: {UNREACHABLE}; MX {MX2} not judged: {UNREACHABLE}"
    )
    assert lists.asked == []


@pytest.mark.parametrize(
    "records",
    [
        {(MX1, "A"): ["198.51.100.25"], (MX2, "A"): ["198.51.100.26"]},
        {(MX1, "AAAA"): ["2001:db8::25"], (MX2, "AAAA"): ["2001:db8::26"]},
    ],
)
def test_mail_hosts_without_a_global_ipv4_address_ask_no_list(world, lists, records):
    world.records = {(D, "MX"): [(10, MX1), (20, MX2)], **records}

    result = _probe()

    assert (result.status, result.reached) == ("unknown", True)
    assert result.message == (
        "no global IPv4 address of the mail hosts: the lists are asked for IPv4"
    )
    assert lists.asked == []


def test_an_address_of_two_mail_hosts_is_asked_once(world, lists):
    world.records[(MX2, "A")] = [A1]

    result = _probe()

    assert result.message == f"1 address not listed on {FREE}"
    assert lists.asked.count((_q(A1, "psbl"), "A")) == 1


def test_at_most_ten_mail_hosts_are_asked(world, lists):
    hosts = [f"mx{i}.example.test" for i in range(12)]
    world.records = {(D, "MX"): [(i, h) for i, h in enumerate(hosts)]}
    world.records.update({(h, "A"): [f"192.0.2.{i + 1}"] for i, h in enumerate(hosts)})

    result = _probe()

    assert result.message == f"10 addresses not listed on {FREE}; 12 MX hosts, the first 10 checked"
    assert _details(result)["mx"] == hosts[:10]
    assert [n for _, n, t in world.asked if t == "A"] == hosts[:10]


def test_at_most_ten_addresses_are_asked(world, lists):
    world.records[(MX1, "A")] = [f"192.0.2.{i}" for i in range(1, 13)]
    world.records[(MX2, "A")] = []

    result = _probe()

    assert (
        result.message == f"10 addresses not listed on {FREE}; 12 addresses, the first 10 checked"
    )
    assert len(_details(result)["addresses"]) == 10
    assert len(lists.zone_asked("psbl")) == 2 + 10


def test_a_run_ends_after_its_deadline(world, monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(dnsbl, "time", SimpleNamespace(monotonic=lambda: clock.now))
    stand_in = Lists(clock)
    monkeypatch.setattr(dnsbl, "list_query", stand_in)

    result = _probe()

    assert result.status == "unknown"
    assert result.message == "; ".join(
        f"{title} not judged: run longer than 45 s"
        for title in ("PSBL", "SpamCop", "UCEPROTECT level 1")
    )
    # Three queries of 20 s each; the fourth would start after 45 s.
    assert len(stand_in.asked) == 3


# --- the query to the lists -----------------------------------------------------------


@pytest.fixture
def stub_resolve(monkeypatch):
    calls = []

    def install(outcome):
        def fake_resolve(self, qname, rdtype, **kwargs):
            calls.append((self.lifetime, qname.to_text(), rdtype, kwargs))
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
        ("A", _rrset("A", "127.0.0.2", "127.0.0.4"), ("127.0.0.2", "127.0.0.4")),
        ("TXT", _rrset("TXT", '"Listed " "by PSBL"'), ("Listed by PSBL",)),
        ("TXT", SimpleNamespace(rrset=[SimpleNamespace(strings=(b"\xc3\xa4",))]), ("��",)),
    ],
)
def test_list_query_reads_the_records(stub_resolve, rdtype, answer, values):
    calls = stub_resolve(answer)

    assert dnsbl.list_query("2.0.0.127.psbl.surriel.com", rdtype) == DnsAnswer(
        AnswerStatus.OK, values
    )
    assert calls == [
        (
            resolve.QUERY_LIFETIME_S,
            "2.0.0.127.psbl.surriel.com.",
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
def test_list_query_tells_what_kind_of_no_answer(stub_resolve, outcome, status):
    stub_resolve(outcome)

    assert dnsbl.list_query("2.0.0.127.psbl.surriel.com", "A") == DnsAnswer(status)


def test_list_query_without_a_system_resolver_is_silent(monkeypatch):
    def no_config(*args, **kwargs):
        raise dns.resolver.NoResolverConfiguration("no nameservers")

    monkeypatch.setattr(dns.resolver, "Resolver", no_config)

    assert dnsbl.list_query("2.0.0.127.psbl.surriel.com", "A") == DnsAnswer(AnswerStatus.SILENT)
