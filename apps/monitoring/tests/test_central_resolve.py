# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rule public/internal for central checks (R-1224), with a fake resolver: no network.

The global addresses in the answers are AS112 addresses (192.175.48.0/24,
2620:4f:8000::/48, both "Globally Reachable: True" at IANA); everything not
global is from the documentation ranges.
"""

import logging
from types import SimpleNamespace

import dns.exception
import dns.name
import dns.resolver
import pytest

from app.central import resolve
from app.central.resolve import AnswerStatus, Reach, ResolverAnswer, classify
from app.core import config

R1 = "192.0.2.53"
R2 = "198.51.100.53"
GLOBAL_A = "192.175.48.1"
GLOBAL_A2 = "192.175.48.6"
GLOBAL_AAAA = "2620:4f:8000::1"
PRIVATE_A = "192.0.2.10"


def _ok(*addresses):
    return ("ok", addresses)


SILENT = ("silent", ())
NXDOMAIN = ("nxdomain", ())
NODATA = ("nodata", ())


@pytest.fixture
def answers(monkeypatch):
    """{(resolver, rdtype): (status, addresses)} for the host under test; a question
    nobody set up fails the test instead of passing as silence."""
    table: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {}
    asked: list[tuple[str, str, str]] = []

    def fake_query(resolver, name, rdtype):
        asked.append((resolver, name.to_text(), rdtype))
        status, addresses = table[(resolver, rdtype)]
        return ResolverAnswer(resolver, AnswerStatus(status), addresses)

    monkeypatch.setattr(resolve, "query", fake_query)
    return SimpleNamespace(table=table, asked=asked)


def _set(answers, resolver, a, aaaa):
    answers.table[(resolver, "A")] = a
    answers.table[(resolver, "AAAA")] = aaaa


def test_both_resolvers_agree_public(answers):
    _set(answers, R1, _ok(GLOBAL_A), _ok(GLOBAL_AAAA))
    _set(answers, R2, _ok(GLOBAL_A, GLOBAL_A2), NODATA)
    result = classify("www.example.com", (R1, R2))
    assert result.reach is Reach.PUBLIC
    assert result.addresses == (GLOBAL_A, GLOBAL_AAAA, GLOBAL_A2)
    assert result.notes == ()
    assert result.message == ""
    assert {(r, t) for r, _, t in answers.asked} == {
        (R1, "A"),
        (R1, "AAAA"),
        (R2, "A"),
        (R2, "AAAA"),
    }
    assert {n for _, n, _ in answers.asked} == {"www.example.com."}


def test_one_silent_resolver_does_not_veto(answers):
    _set(answers, R1, SILENT, SILENT)
    _set(answers, R2, _ok(GLOBAL_A), NODATA)
    result = classify("www.example.com", (R1, R2))
    assert result.reach is Reach.PUBLIC
    assert result.addresses == (GLOBAL_A,)
    assert result.notes == (f"resolver {R1} silent",)


def test_all_resolvers_silent(answers):
    _set(answers, R1, SILENT, SILENT)
    _set(answers, R2, SILENT, SILENT)
    result = classify("www.example.com", (R1, R2))
    assert result.reach is Reach.RESOLVERS_UNREACHABLE
    assert result.addresses == ()
    assert result.message == resolve.RESOLVERS_UNREACHABLE_MESSAGE
    assert result.notes == (f"resolver {R1} silent", f"resolver {R2} silent")


def test_a_resolver_that_does_not_know_the_name_makes_it_internal(answers):
    _set(answers, R1, _ok(GLOBAL_A), NODATA)
    _set(answers, R2, NXDOMAIN, NXDOMAIN)
    result = classify("intern.example.com", (R1, R2))
    assert result.reach is Reach.NOT_PUBLIC
    assert result.addresses == ()
    assert result.message == resolve.NOT_PUBLIC_MESSAGE
    assert result.notes == (f"resolver {R2}: name unknown",)


def test_a_resolver_without_an_address_makes_it_internal(answers):
    _set(answers, R1, _ok(GLOBAL_A), NODATA)
    _set(answers, R2, NODATA, NODATA)
    result = classify("www.example.com", (R1, R2))
    assert result.reach is Reach.NOT_PUBLIC
    assert result.notes == (f"resolver {R2}: no address",)


def test_only_global_addresses_are_handed_on(answers):
    _set(answers, R1, _ok(PRIVATE_A, GLOBAL_A), NODATA)
    _set(answers, R2, _ok(GLOBAL_A, PRIVATE_A), NODATA)
    result = classify("www.example.com", (R1, R2))
    assert result.reach is Reach.PUBLIC
    assert result.addresses == (GLOBAL_A,)


def test_no_global_address_is_internal(answers):
    _set(answers, R1, _ok(PRIVATE_A), _ok("fd00::1"))
    _set(answers, R2, _ok(PRIVATE_A), NODATA)
    result = classify("nas.example.com", (R1, R2))
    assert result.reach is Reach.NOT_PUBLIC
    assert result.addresses == ()
    assert result.notes == ("no global address",)


def test_mapped_answer_connects_over_ipv4_nat64_stays_ipv6(answers):
    _set(answers, R1, NODATA, _ok(f"::ffff:{GLOBAL_A}", "64:ff9b::c0af:3006"))
    _set(answers, R2, _ok(GLOBAL_A), NODATA)
    result = classify("www.example.com", (R1, R2))
    assert result.reach is Reach.PUBLIC
    assert result.addresses == (GLOBAL_A, "64:ff9b::c0af:3006")


def test_mapped_private_answer_is_not_global(answers):
    _set(answers, R1, NODATA, _ok(f"::ffff:{PRIVATE_A}"))
    _set(answers, R2, NODATA, _ok(f"::ffff:{PRIVATE_A}"))
    assert classify("www.example.com", (R1, R2)).reach is Reach.NOT_PUBLIC


@pytest.mark.parametrize(
    ("host", "reach", "addresses"),
    [
        (GLOBAL_A, Reach.PUBLIC, (GLOBAL_A,)),
        (GLOBAL_AAAA, Reach.PUBLIC, (GLOBAL_AAAA,)),
        (f"::ffff:{GLOBAL_A}", Reach.PUBLIC, (GLOBAL_A,)),
        (PRIVATE_A, Reach.NOT_PUBLIC, ()),
        ("fe80::1", Reach.NOT_PUBLIC, ()),
    ],
)
def test_ip_literal_asks_no_resolver(answers, host, reach, addresses):
    result = classify(host, (R1, R2))
    assert result.reach is reach
    assert result.addresses == addresses
    assert answers.asked == []


def test_invalid_name_asks_no_resolver(answers):
    result = classify("a" * 64 + ".example.com", (R1, R2))
    assert result.reach is Reach.NOT_PUBLIC
    assert result.notes == ("invalid host name",)
    assert answers.asked == []


def test_default_resolvers_come_from_config(answers, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_RESOLVERS", (R2,))
    _set(answers, R2, _ok(GLOBAL_A), NODATA)
    assert classify("www.example.com").addresses == (GLOBAL_A,)
    assert {r for r, _, _ in answers.asked} == {R2}


@pytest.mark.parametrize(
    ("a", "aaaa", "status"),
    [
        (_ok(GLOBAL_A), SILENT, AnswerStatus.OK),
        (NODATA, _ok(GLOBAL_AAAA), AnswerStatus.OK),
        (NXDOMAIN, SILENT, AnswerStatus.NXDOMAIN),
        (NODATA, SILENT, AnswerStatus.SILENT),
        (NODATA, NODATA, AnswerStatus.NODATA),
    ],
)
def test_ask_merges_a_and_aaaa(answers, a, aaaa, status):
    _set(answers, R1, a, aaaa)
    assert resolve.ask(R1, dns.name.from_text("www.example.com")).status is status


# ---- query: what dnspython answers, mapped to a status ----------------------


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


def test_query_asks_only_the_given_resolver_without_search(stub_resolve):
    calls = stub_resolve(SimpleNamespace(rrset=[SimpleNamespace(address=GLOBAL_A)]))
    answer = resolve.query(R1, dns.name.from_text("www.example.com"), "A")
    assert answer == ResolverAnswer(R1, AnswerStatus.OK, (GLOBAL_A,))
    assert calls == [
        (
            [R1],
            resolve.QUERY_LIFETIME_S,
            "www.example.com.",
            "A",
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
        (dns.exception.DNSException(), AnswerStatus.SILENT),
        (OSError("network unreachable"), AnswerStatus.SILENT),
    ],
)
def test_query_maps_outcomes(stub_resolve, outcome, status):
    stub_resolve(outcome)
    answer = resolve.query(R1, dns.name.from_text("www.example.com"), "AAAA")
    assert answer.status is status
    assert answer.addresses == ()


# ---- configuration -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected", "warns"),
    [
        ("", ("9.9.9.9", "1.1.1.1"), False),
        ("  ", ("9.9.9.9", "1.1.1.1"), False),
        ("9.9.9.9, 1.1.1.1 ,9.9.9.9", ("9.9.9.9", "1.1.1.1"), False),
        ("2620:00fe::fe,2620:fe::fe", ("2620:fe::fe",), False),
        ("resolver.example,1.1.1.1", ("1.1.1.1",), True),
        ("resolver.example", ("9.9.9.9", "1.1.1.1"), True),
    ],
)
def test_public_resolvers_setting(caplog, raw, expected, warns):
    with caplog.at_level(logging.WARNING, logger="monitor.config"):
        assert config._public_resolvers(raw) == expected
    assert bool(caplog.records) is warns


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("  Abc123xyz  ", "Abc123xyz"),
        ("a" * 63, "a" * 63),
        ("a" * 64, ""),
        ("abc.def", ""),
        ("abc-def", ""),
        ("abcä", ""),
    ],
)
def test_spamhaus_dqs_key_is_one_label_and_never_logged(caplog, raw, expected):
    with caplog.at_level(logging.DEBUG, logger="monitor.config"):
        assert config._spamhaus_dqs_key(raw) == expected
    if raw.strip():
        assert all(raw.strip() not in r.getMessage() for r in caplog.records)
    assert bool(caplog.records) is (bool(raw.strip()) and not expected)
