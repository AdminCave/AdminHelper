# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""CAA (RFC 8659) for the sensor tls (R-1224), with a fake resolver: no network."""

import ipaddress
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import dns.exception
import dns.name
import dns.resolver
import dns.rrset
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.central import ari, caa
from app.central.caa import CaaAnswer, Record
from app.central.resolve import AnswerStatus

NOW = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
R1 = "192.0.2.53"
R2 = "198.51.100.53"
RESOLVERS = (R1, R2)
LE = ari.KNOWN_CAS[0]
KEY = ec.generate_private_key(ec.SECP256R1())


def _leaf(*names):
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "leaf")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "E7")]))
        .public_key(KEY.public_key())
        .serial_number(1)
        .not_valid_before(NOW - timedelta(days=30))
        .not_valid_after(NOW + timedelta(days=60))
    )
    if names:
        sans = [
            x509.IPAddress(ipaddress.ip_address(n[3:])) if n.startswith("ip:") else x509.DNSName(n)
            for n in names
        ]
        builder = builder.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    return builder.sign(KEY, hashes.SHA256())


def _set(*records):
    """CAA records as (flags, tag, value)."""
    return CaaAnswer(AnswerStatus.OK, tuple(Record(*r) for r in records))


@pytest.fixture
def dns_(monkeypatch):
    """{name: CaaAnswer}; a name not in the table has no CAA records (NODATA), a
    resolver in `silent` answers nothing."""
    fake = SimpleNamespace(table={}, silent=set(), asked=[])

    def fake_query(resolver, name):
        fake.asked.append((resolver, name.to_text(omit_final_dot=True)))
        if resolver in fake.silent:
            return CaaAnswer(AnswerStatus.SILENT)
        return fake.table.get(name.to_text(omit_final_dot=True), CaaAnswer(AnswerStatus.NODATA))

    monkeypatch.setattr(caa, "query", fake_query)
    return fake


def _names(fake):
    return [name for _, name in fake.asked]


def _evaluate(host="www.example.com", leaf=None, prev=None, now=NOW, ca=LE):
    return caa.evaluate(leaf or _leaf(host), host, ca, prev, now, RESOLVERS)


def _at(delta):
    return (NOW + delta).isoformat().replace("+00:00", "Z")


# --- the relevant set ---


def test_the_issuer_permitted_by_the_name_s_own_set(dns_):
    dns_.table["www.example.com"] = _set((0, "issue", "letsencrypt.org"))

    state, warning = _evaluate()

    assert warning is None
    assert state == {
        "subject": "www.example.com",
        "wildcard": False,
        "ca": "Let's Encrypt",
        "checked_at": _at(timedelta(0)),
        "next_at": _at(caa.RECHECK),
        "name": "www.example.com",
        "allowed": ["letsencrypt.org"],
        "permitted": True,
    }
    assert dns_.asked == [(R1, "www.example.com")]


def test_the_climb_stops_at_the_first_set(dns_):
    dns_.table["www.example.com"] = CaaAnswer(AnswerStatus.NXDOMAIN)
    dns_.table["example.com"] = _set((0, "issue", "pki.goog"))
    dns_.table["com"] = _set((0, "issue", "letsencrypt.org"))

    state, warning = _evaluate()

    assert _names(dns_) == ["www.example.com", "example.com"]
    assert (state["name"], state["permitted"]) == ("example.com", False)
    assert warning == "CAA of example.com does not permit Let's Encrypt (permitted: pki.goog)"


def test_the_climb_ends_at_the_top_level_domain(dns_):
    state, warning = _evaluate()

    assert _names(dns_) == ["www.example.com", "example.com", "com"]
    assert (state["name"], state["allowed"], state["permitted"]) == (None, None, True)
    assert warning is None


def test_a_name_of_too_many_labels_gets_no_statement(dns_):
    host = ".".join(["a"] * caa.MAX_LABELS) + ".com"

    state, warning = _evaluate(host)

    assert dns_.asked == []
    assert (state["error"], warning) == (f"more than {caa.MAX_LABELS} labels", None)


# --- issue and issuewild ---


@pytest.mark.parametrize(
    ("records", "allowed", "permitted"),
    [
        ([(0, "issue", ";")], [], False),
        ([(0, "issue", "")], [], False),
        ([(0, "issue", "LetsEncrypt.ORG")], ["letsencrypt.org"], True),
        ([(0, "issue", "letsencrypt.org; validationmethods=dns-01")], ["letsencrypt.org"], True),
        (
            [(0, "issue", " letsencrypt.org ; accounturi=https://acme.example/acct/1 ; x=y")],
            ["letsencrypt.org"],
            True,
        ),
        # outside the grammar: permits nobody
        ([(0, "issue", "lets encrypt.org")], [], False),
        ([(0, "issue", "-letsencrypt.org")], [], False),
        ([(0, "issue", "letsencrypt.org.")], [], False),
        ([(0, "issue", "letsencrypt.org; =dns-01")], [], False),
        ([(0, "issue", "letsencrypt.org�")], [], False),
        # one valid issue property is enough
        ([(0, "issue", "bad value!"), (0, "issue", "letsencrypt.org")], ["letsencrypt.org"], True),
        ([(0, "issue", "pki.goog"), (0, "issue", "pki.goog")], ["pki.goog"], False),
        # no issue property: no restriction for a name without wildcard
        ([(0, "iodef", "mailto:caa@example.com")], None, True),
        ([(0, "issuewild", ";")], None, True),
        ([(0, "issuewild", ";"), (0, "issue", "letsencrypt.org")], ["letsencrypt.org"], True),
        # a non-critical unknown tag is ignored
        ([(0, "tbs", "x"), (0, "issue", "letsencrypt.org")], ["letsencrypt.org"], True),
    ],
)
def test_the_issue_properties_decide(dns_, records, allowed, permitted):
    dns_.table["www.example.com"] = _set(*records)

    state, warning = _evaluate()

    assert (state["allowed"], state["permitted"]) == (allowed, permitted)
    assert (warning is None) is permitted


def test_permitting_nobody_says_so(dns_):
    dns_.table["www.example.com"] = _set((0, "issue", ";"))

    assert _evaluate()[1] == (
        "CAA of www.example.com does not permit Let's Encrypt (permitted: nobody)"
    )


def test_the_listed_issuers_are_capped_but_all_count(dns_):
    others = [(0, "issue", f"ca{i}.example") for i in range(caa.MAX_LISTED + 1)]
    dns_.table["www.example.com"] = _set(*others, (0, "issue", "letsencrypt.org"))

    state, warning = _evaluate()

    assert len(state["allowed"]) == caa.MAX_LISTED
    assert "letsencrypt.org" not in state["allowed"]
    assert (state["permitted"], warning) == (True, None)


def test_a_critical_unknown_tag_permits_no_ca(dns_):
    dns_.table["www.example.com"] = _set((0, "issue", "letsencrypt.org"), (128, "tbs", "x"))

    state, warning = _evaluate()

    assert (state["permitted"], state["critical_tag"]) == (False, "tbs")
    assert warning == (
        "CAA of www.example.com carries the unknown critical tag tbs: no CA may issue"
    )


def test_a_critical_known_tag_is_no_obstacle(dns_):
    dns_.table["www.example.com"] = _set((128, "issue", "letsencrypt.org"))

    state, _ = _evaluate()

    assert state["permitted"] is True and "critical_tag" not in state


@pytest.mark.parametrize(
    ("records", "permitted"),
    [
        ([(0, "issue", "pki.goog"), (0, "issuewild", "letsencrypt.org")], True),
        ([(0, "issue", "letsencrypt.org"), (0, "issuewild", "pki.goog")], False),
        ([(0, "issue", "letsencrypt.org"), (0, "issuewild", ";")], False),
        # without issuewild the issue properties hold for the wildcard too
        ([(0, "issue", "letsencrypt.org")], True),
        ([(0, "issue", "pki.goog")], False),
    ],
)
def test_a_wildcard_is_looked_up_at_its_parent_with_issuewild(dns_, records, permitted):
    dns_.table["example.com"] = _set(*records)

    state, _ = _evaluate(leaf=_leaf("*.example.com"))

    assert _names(dns_) == ["example.com"]
    assert (state["subject"], state["wildcard"], state["permitted"]) == (
        "example.com",
        True,
        permitted,
    )


def test_an_exact_name_beats_the_wildcard(dns_):
    dns_.table["www.example.com"] = _set((0, "issuewild", ";"))

    state, _ = _evaluate(leaf=_leaf("*.example.com", "WWW.Example.com"))

    assert (state["subject"], state["wildcard"], state["permitted"]) == (
        "www.example.com",
        False,
        True,
    )


@pytest.mark.parametrize(
    ("host", "leaf", "ca"),
    [
        ("192.0.2.10", _leaf("ip:192.0.2.10"), LE),
        ("2001:db8::10", _leaf("ip:2001:db8::10"), LE),
        ("www.example.com", _leaf("www.example.com"), None),
        ("www.example.com", _leaf("mail.example.com"), LE),
        # a wildcard covers one label only
        ("a.www.example.com", _leaf("*.example.com"), LE),
        ("www.example.com", _leaf(), LE),
    ],
)
def test_no_statement_without_a_domain_name_a_known_ca_or_a_covering_san(dns_, host, leaf, ca):
    assert caa.evaluate(leaf, host, ca, None, NOW, RESOLVERS) == (None, None)
    assert dns_.asked == []


# --- resolvers ---


def test_a_silent_resolver_is_followed_by_the_next(dns_):
    dns_.silent.add(R1)
    dns_.table["www.example.com"] = _set((0, "issue", "pki.goog"))

    state, warning = _evaluate()

    assert dns_.asked == [(R1, "www.example.com"), (R2, "www.example.com")]
    assert state["permitted"] is False and warning is not None


def test_silent_resolvers_give_no_statement_and_a_retry_in_an_hour(dns_):
    dns_.silent.update(RESOLVERS)

    state, warning = _evaluate()

    assert warning is None and "permitted" not in state
    assert state["error"] == "public resolvers unreachable"
    assert state["next_at"] == _at(caa.RETRY_NO_ANSWER)


def test_without_an_answer_the_last_verdict_stays(dns_):
    dns_.table["www.example.com"] = _set((0, "issue", "pki.goog"))
    state, _ = _evaluate()
    dns_.silent.update(RESOLVERS)

    later = NOW + caa.RECHECK
    state, warning = _evaluate(prev=state, now=later)

    assert (state["permitted"], state["name"]) == (False, "www.example.com")
    assert state["error"] == "public resolvers unreachable"
    assert datetime.fromisoformat(state["next_at"]) == later + caa.RETRY_NO_ANSWER
    assert warning == "CAA of www.example.com does not permit Let's Encrypt (permitted: pki.goog)"


def test_an_answer_clears_the_error(dns_):
    dns_.silent.update(RESOLVERS)
    state, _ = _evaluate()
    dns_.silent.clear()

    state, _ = _evaluate(prev=state, now=NOW + caa.RETRY_NO_ANSWER)

    assert "error" not in state and state["permitted"] is True


# --- when to ask ---


def test_a_state_that_is_not_due_is_used_without_asking(dns_):
    dns_.table["www.example.com"] = _set((0, "issue", "pki.goog"))
    state, _ = _evaluate()
    dns_.asked.clear()
    dns_.table.clear()

    again, warning = _evaluate(prev=state, now=NOW + caa.RECHECK - timedelta(seconds=1))

    assert dns_.asked == [] and again == state and warning is not None


def test_a_due_state_is_asked_again(dns_):
    state, _ = _evaluate()
    dns_.table["www.example.com"] = _set((0, "issue", "pki.goog"))

    state, warning = _evaluate(prev=state, now=NOW + caa.RECHECK)

    assert state["permitted"] is False and warning is not None


@pytest.mark.parametrize(
    "other",
    [
        {"subject": "mail.example.com"},
        {"wildcard": True},
        {"ca": "Google Trust Services"},
    ],
)
def test_the_state_of_another_name_or_ca_is_not_used(dns_, other):
    prev = {
        "subject": "www.example.com",
        "wildcard": False,
        "ca": "Let's Encrypt",
        "next_at": _at(caa.RECHECK),
        "permitted": False,
        "name": "www.example.com",
        **other,
    }

    state, warning = _evaluate(prev=prev)

    assert dns_.asked and state["permitted"] is True and warning is None


# --- query ---


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


def test_query_reads_the_records_with_tags_in_lower_case(stub_resolve):
    rrset = dns.rrset.from_text(
        "example.com.", 300, "IN", "CAA", '128 ISSUE "LetsEncrypt.org"', '0 issuewild ";"'
    )
    calls = stub_resolve(SimpleNamespace(rrset=rrset))

    answer = caa.query(R1, dns.name.from_text("example.com"))

    assert answer.status is AnswerStatus.OK
    assert sorted(answer.records, key=lambda r: r.tag) == [
        Record(128, "issue", "LetsEncrypt.org"),
        Record(0, "issuewild", ";"),
    ]
    assert calls == [
        (
            [R1],
            caa.resolve.QUERY_LIFETIME_S,
            "example.com.",
            "CAA",
            {"raise_on_no_answer": False, "search": False},
        )
    ]


def test_query_keeps_a_non_ascii_value_outside_the_grammar(stub_resolve):
    record = SimpleNamespace(flags=0, tag=b"issue", value="letsencrypt.orgä".encode())
    stub_resolve(SimpleNamespace(rrset=[record]))

    answer = caa.query(R1, dns.name.from_text("example.com"))

    assert caa.permitted_issuers(answer.records, wildcard=False) == ((), None)


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

    answer = caa.query(R1, dns.name.from_text("example.com"))

    assert (answer.status, answer.records) == (status, ())
