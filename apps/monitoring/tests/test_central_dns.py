# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensor dns of central checks (R-1224): resolver comparison, baseline, the hourly
look at the zone's name servers, DNSSEC.

The network is a stand-in: `exchange` answers from the World below, which plays the
two public resolvers and the zone's name servers; the rule public/internal for the
name servers and the spacing limits are stand-ins as well.
"""

from datetime import datetime, timedelta, timezone

import dns.exception
import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rrset
import pytest

from app.central import dns as dns_sensor
from app.central import resolve
from app.central.limits import Limits
from app.central.resolve import AnswerStatus, Classification, Reach, ResolverAnswer
from app.core.time import iso_utc

R1, R2 = "192.0.2.53", "198.51.100.53"
RESOLVERS = (R1, R2)
HOST = "www.example.test"
ZONE = "example.test"
V4, V6 = "192.0.2.10", "2001:db8::10"
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
NAME_SERVERS = {"ns1.example.test": ("192.0.2.1",), "ns2.example.net": ("198.51.100.2",)}


def _rrset(name, rdtype, *texts, ttl=300):
    return dns.rrset.from_text(name + ".", ttl, "IN", rdtype, *texts)


def _reply(qname, rdtype, *, rcode=dns.rcode.NOERROR, aa=False, answer=(), authority=()):
    response = dns.message.make_response(dns.message.make_query(qname, rdtype))
    response.set_rcode(rcode)
    if aa:
        response.flags |= dns.flags.AA
    response.answer.extend(answer)
    response.authority.extend(authority)
    return response


def _soa(zone):
    return _rrset(zone, "SOA", f"ns1.{zone}. hostmaster.{zone}. 2026111201 7200 3600 1209600 300")


def _sigtime(moment):
    return moment.strftime("%Y%m%d%H%M%S")


class World:
    """The resolvers and the name servers of example.test, healthy unless a test says otherwise."""

    def __init__(self):
        self.addresses = {HOST: (V4, V6)}
        self.aliases: set[str] = set()
        self.name_servers = dict(NAME_SERVERS)
        self.signed = True
        # address -> (inception, expiration) of the signature it serves over HOST
        self.sigs: dict[str, tuple[datetime, datetime]] = {}
        self.signer = ZONE
        self.lame: set[str] = set()
        self.refusing: set[str] = set()
        self.silent: set[str] = set()
        self.down: set[str] = set()  # resolvers without reply
        self.servfail: set[str] = set()  # resolvers that fail for HOST without CD
        self.servfail_cd: set[str] = set()  # ... and with CD as well
        self.no_address: set[str] = set()
        self.unreachable_ns: set[str] = set()
        self.refused_turns: set[str] = set()
        self.queries: list[tuple] = []
        self.turns: list[str] = []
        self.classified: list[str] = []
        for addresses in NAME_SERVERS.values():
            for address in addresses:
                self.sigs[address] = (NOW - timedelta(days=4), NOW + timedelta(days=10))

    # the network

    def exchange(
        self, server, qname, rdtype, *, recursion=True, checking_disabled=False, dnssec=False
    ):
        name = qname.to_text(omit_final_dot=True)
        self.queries.append((server, name, rdtype, recursion, checking_disabled, dnssec))
        if server in RESOLVERS:
            return (
                None
                if server in self.down
                else self._resolver(server, qname, name, rdtype, checking_disabled)
            )
        return (
            None if server in self.silent else self._authority(server, qname, name, rdtype, dnssec)
        )

    def _resolver(self, server, qname, name, rdtype, cd):
        if rdtype in ("A", "AAAA"):
            failing = server in self.servfail and (not cd or server in self.servfail_cd)
            if failing:
                return _reply(qname, rdtype, rcode=dns.rcode.SERVFAIL)
            return _reply(qname, rdtype, answer=[_rrset(name, "A", V4)])
        if rdtype == "SOA":
            if name in self.aliases:
                return _reply(
                    qname,
                    rdtype,
                    answer=[_rrset(name, "CNAME", "edge.cdn.test.")],
                    authority=[_soa("cdn.test")],
                )
            if name == ZONE:
                return _reply(qname, rdtype, answer=[_soa(ZONE)])
            return _reply(qname, rdtype, authority=[_soa(ZONE)])
        if rdtype == "NS":
            servers = [f"{ns}." for ns in self.name_servers]
            return _reply(qname, rdtype, answer=[_rrset(name, "NS", *servers)] if servers else [])
        if rdtype == "DS":
            ds = _rrset(name, "DS", "12345 13 2 " + "ab" * 32)
            return _reply(qname, rdtype, answer=[ds] if self.signed else [])
        raise AssertionError(f"unexpected question {rdtype} to a resolver")

    def _authority(self, address, qname, name, rdtype, dnssec):
        if address in self.refusing:
            return _reply(qname, rdtype, rcode=dns.rcode.REFUSED)
        if address in self.lame:
            return _reply(qname, rdtype, authority=[_rrset(ZONE, "NS", "elsewhere.test.")])
        if rdtype == "SOA":
            return _reply(qname, rdtype, aa=True, answer=[_soa(ZONE)])
        assert dnssec, "a name server is asked for the host only for its signatures"
        answer = [_rrset(name, rdtype, V4 if rdtype == "A" else V6)]
        if address in self.sigs:
            inception, expiration = self.sigs[address]
            sig = (
                f"{rdtype} 13 3 300 {_sigtime(expiration)} {_sigtime(inception)} "
                f"12345 {self.signer}. AAAA"
            )
            answer.append(_rrset(name, "RRSIG", sig))
        return _reply(qname, rdtype, aa=True, answer=answer)

    def classify(self, host, resolvers=None):
        self.classified.append(host)
        if host in self.unreachable_ns:
            return Classification(Reach.RESOLVERS_UNREACHABLE)
        if host in self.no_address:
            return Classification(Reach.NOT_PUBLIC, notes=("not a global address",))
        return Classification(Reach.PUBLIC, self.name_servers[host])

    def address_turn(self, address):
        self.turns.append(address)
        return address not in self.refused_turns

    # what the tests read

    def asked_servers(self):
        return [q for q in self.queries if q[0] not in RESOLVERS]


@pytest.fixture()
def world(monkeypatch):
    w = World()
    monkeypatch.setattr(dns_sensor, "exchange", w.exchange)
    monkeypatch.setattr(resolve, "classify", w.classify)
    return w


def _rule(*answers):
    """The rule's view: (resolver, addresses) pairs, None for a silent resolver."""
    answers = answers or ((R1, (V4, V6)), (R2, (V4, V6)))
    resolved = tuple(
        ResolverAnswer(r, AnswerStatus.SILENT)
        if a is None
        else ResolverAnswer(r, AnswerStatus.OK, tuple(a))
        for r, a in answers
    )
    addresses = tuple(dict.fromkeys(x for a in resolved for x in a.addresses))
    return Classification(Reach.PUBLIC, addresses, resolved)


def _probe(world, rule=None, params=None, prev=None, now=NOW, host=HOST):
    return dns_sensor.probe(
        host, rule or _rule(), params or {}, prev, now=now, limits=world, resolvers=RESOLVERS
    )


def _looked(world, now=NOW):
    """The details of a run that made the hourly look, as the next run's prev."""
    return _probe(world, now=now).details


# --- resolvers and baseline ---


def test_agreeing_resolvers_are_ok_and_the_first_complete_answer_becomes_the_baseline(world):
    result = _probe(world)

    assert (result.status, result.message) == ("ok", f"resolves to {V4}, {V6}")
    assert result.reached is True
    assert result.metrics == {"resolvers_agree": 1.0}
    assert result.details["baseline"] == {"addresses": [V4, V6], "since": iso_utc(NOW)}
    assert result.details["answers"] == {R1: [V4, V6], R2: [V4, V6]}


def test_disagreeing_resolvers_warn(world):
    result = _probe(world, _rule((R1, (V4,)), (R2, ("192.0.2.11",))))

    assert result.status == "warning"
    assert result.message == f"resolvers disagree ({R1}: {V4}; {R2}: 192.0.2.11)"
    assert result.metrics == {"resolvers_agree": 0.0}


def test_a_single_answering_resolver_gives_no_agreement_and_no_baseline(world):
    result = _probe(world, _rule((R1, (V4,)), (R2, None)))

    assert result.status == "ok"
    assert result.metrics == {}
    assert "baseline" not in result.details


def test_a_changed_address_warns_against_the_baseline_which_stays(world):
    baseline = {"addresses": [V4], "since": "2026-11-01T08:00:00Z"}

    result = _probe(
        world, _rule((R1, ("192.0.2.11",)), (R2, ("192.0.2.11",))), prev={"baseline": baseline}
    )

    assert result.status == "warning"
    assert result.message == f"addresses changed: new 192.0.2.11; gone {V4}"
    assert result.details["baseline"] == baseline


def test_an_incomplete_answer_reports_only_new_addresses(world):
    prev = {"baseline": {"addresses": [V4, "192.0.2.12"], "since": "2026-11-01T08:00:00Z"}}

    quiet = _probe(world, _rule((R1, (V4,)), (R2, None)), prev=prev)
    added = _probe(world, _rule((R1, (V4, "192.0.2.11")), (R2, None)), prev=prev)

    assert quiet.status == "ok"
    assert added.message == "addresses changed: new 192.0.2.11"


def test_expected_addresses_replace_the_baseline(world):
    prev = {"baseline": {"addresses": [V4, V6], "since": "2026-11-01T08:00:00Z"}}

    result = _probe(world, params={"expected": [V4]}, prev=prev)

    assert result.message == f"addresses changed: new {V6}"
    assert "baseline" not in result.details


def test_expected_addresses_compare_in_normal_form(world):
    result = _probe(world, params={"expected": ["2001:DB8:0::10", V4]})

    assert result.status == "ok"


@pytest.mark.parametrize(
    "baseline",
    ["x", {"addresses": "192.0.2.10"}, {"addresses": ["nope"]}, {"addresses": []}],
)
def test_a_broken_stored_baseline_is_learned_anew(world, baseline):
    result = _probe(world, prev={"baseline": baseline})

    assert result.status == "ok"
    assert result.details["baseline"] == {"addresses": [V4, V6], "since": iso_utc(NOW)}


def test_long_address_lists_are_cut(world):
    many = tuple(f"192.0.2.{i}" for i in range(20, 32))

    result = _probe(world, _rule((R1, many), (R2, many)))

    assert result.message.endswith("192.0.2.27 (+4)")


# --- a resolver that stayed silent for the rule ---


def test_a_resolver_that_answers_only_with_checking_disabled_is_critical(world):
    world.servfail.add(R2)

    result = _probe(world, _rule((R1, (V4, V6)), (R2, None)))

    assert result.status == "critical"
    assert result.message.startswith(f"DNSSEC validation fails at resolver {R2}")
    asked = [q for q in world.queries if q[0] == R2 and q[2] == "A"]
    assert [q[4] for q in asked] == [False, True]  # without, then with CD


def test_a_resolver_that_fails_with_checking_disabled_too_warns(world):
    world.servfail.add(R2)
    world.servfail_cd.add(R2)

    result = _probe(world, _rule((R1, (V4, V6)), (R2, None)))

    assert result.status == "warning"
    assert result.message == f"resolver {R2} cannot resolve {HOST} (SERVFAIL)"


@pytest.mark.parametrize("down", [True, False])
def test_a_resolver_that_answers_again_or_not_at_all_is_no_finding(world, down):
    if down:
        world.down.add(R2)

    result = _probe(world, _rule((R1, (V4, V6)), (R2, None)))

    assert result.status == "ok"


def test_the_diagnosis_names_a_validation_failure(world):
    world.servfail.update(RESOLVERS)

    message = dns_sensor.diagnose_silence(HOST, RESOLVERS)

    assert message == "DNSSEC validation fails: the resolvers answer only with checking disabled"


def test_the_diagnosis_names_a_name_every_resolver_fails_for(world):
    world.servfail.update(RESOLVERS)
    world.servfail_cd.update(RESOLVERS)

    assert dns_sensor.diagnose_silence(HOST, RESOLVERS) == f"{HOST} cannot be resolved (SERVFAIL)"


@pytest.mark.parametrize("down", [{R1, R2}, {R1}])
def test_without_a_reply_from_every_resolver_the_diagnosis_says_nothing(world, down):
    world.servfail.update(RESOLVERS)
    world.servfail_cd.update(RESOLVERS)
    world.down.update(down)

    assert dns_sensor.diagnose_silence(HOST, RESOLVERS) is None


def test_the_diagnosis_says_nothing_about_an_invalid_name(world):
    assert dns_sensor.diagnose_silence("a" * 64 + ".example.test", RESOLVERS) is None
    assert world.queries == []


# --- the hourly look ---


def test_the_look_records_each_name_server_asked_without_recursion(world):
    zone = _probe(world).details["zone"]

    assert zone["name"] == ZONE and zone["signed"] is True
    assert zone["checked_at"] == iso_utc(NOW)
    assert zone["next_at"] == iso_utc(NOW + timedelta(hours=1))
    first = zone["servers"][0]
    assert first["name"] == "ns1.example.test" and first["address"] == "192.0.2.1"
    assert (first["state"], first["serial"]) == ("ok", 2026111201)
    assert first["sig_expires"] == iso_utc(NOW + timedelta(days=10))
    assert first["sig_inception"] == iso_utc(NOW - timedelta(days=4))
    assert all(q[3] is False for q in world.asked_servers())
    assert {q[2] for q in world.asked_servers()} == {"SOA", "A"}
    assert sorted(world.turns) == ["192.0.2.1", "198.51.100.2"]


def test_between_two_looks_the_stored_state_gives_the_verdict(world):
    prev = _looked(world)
    world.queries.clear()
    world.lame.add("198.51.100.2")  # not seen until the next look

    later = _probe(world, prev=prev, now=NOW + timedelta(minutes=30))
    due = _probe(world, prev=prev, now=NOW + timedelta(hours=1))

    assert later.status == "ok"
    assert later.details["zone"] == prev["zone"]
    assert due.status == "warning"
    assert "ns2.example.net not authoritative for example.test" in due.message


@pytest.mark.parametrize("kind", ["lame", "refusing"])
def test_a_server_that_does_not_answer_with_authority_is_lame(world, kind):
    getattr(world, kind).add("198.51.100.2")

    result = _probe(world)

    assert result.status == "warning"
    assert result.message == (
        "name server ns2.example.net not authoritative for example.test (lame delegation)"
    )


def test_a_server_without_a_global_address_warns(world):
    world.no_address.add("ns2.example.net")

    result = _probe(world)

    assert result.message == "name server ns2.example.net without a global address"
    assert world.turns == ["192.0.2.1"]


def test_a_silent_server_warns_when_another_answers(world):
    world.silent.add("198.51.100.2")

    result = _probe(world)

    assert result.message == "name server ns2.example.net not answering"
    # one lost datagram is no dead server: the one address is asked twice
    assert [q[0] for q in world.asked_servers() if q[2] == "SOA"].count("198.51.100.2") == 2


def test_no_answer_from_any_server_is_only_recorded(world):
    world.silent.update({"192.0.2.1", "198.51.100.2"})

    result = _probe(world)

    assert result.status == "ok"
    assert {s["state"] for s in result.details["zone"]["servers"]} == {"silent"}


def test_the_second_address_of_a_server_stands_in_for_a_silent_first(world):
    world.name_servers["ns2.example.net"] = ("198.51.100.2", "2001:db8::2")
    world.sigs["2001:db8::2"] = world.sigs["198.51.100.2"]
    world.silent.add("198.51.100.2")

    result = _probe(world)

    assert result.status == "ok"
    entry = result.details["zone"]["servers"][1]
    assert (entry["state"], entry["address"]) == ("ok", "2001:db8::2")


def test_spacing_postpones_the_whole_look_and_keeps_the_old_state(world):
    prev = _looked(world)
    world.refused_turns.add("198.51.100.2")
    later = NOW + timedelta(hours=1)

    zone = _probe(world, prev=prev, now=later).details["zone"]

    assert zone["servers"] == prev["zone"]["servers"]
    assert zone["error"] == "name server spacing"
    assert zone["next_at"] == iso_utc(later + timedelta(minutes=15))


@pytest.mark.parametrize("cause", ["resolvers", "name server"])
def test_unreachable_resolvers_postpone_the_look(world, cause):
    if cause == "resolvers":
        world.down.update(RESOLVERS)
    else:
        world.unreachable_ns.add("ns2.example.net")

    result = _probe(world)

    assert result.status == "ok"
    assert result.details["zone"]["error"] == "public resolvers unreachable"
    assert "servers" not in result.details["zone"]


def test_an_alias_is_looked_up_in_the_zone_of_its_parent(world):
    world.aliases.add(HOST)

    assert _probe(world).details["zone"]["name"] == ZONE


def test_a_name_at_the_zone_apex_is_its_own_zone(world):
    result = _probe(world, host=ZONE)

    assert result.details["zone"]["name"] == ZONE


def test_the_name_server_list_is_capped(world):
    world.name_servers = {f"ns{i}.example.test": (f"192.0.2.{i}",) for i in range(1, 11)}
    world.sigs = {}
    world.signed = False

    zone = _probe(world).details["zone"]

    assert len(zone["servers"]) == 8 and zone["unchecked"] == 2
    assert len(world.turns) == 8


def test_name_servers_on_one_address_ask_it_once(world):
    # A real spacing that never lets time pass: a second turn on the address within the
    # look would wait, the sixth one past SPACING_WAIT_S (R-1381).
    world.name_servers = {f"ns{i}.example.test": ("192.0.2.1",) for i in range(1, 9)}
    limits = Limits(clock=lambda: 0.0, sleep=lambda _: None)

    result = dns_sensor.probe(HOST, _rule(), {}, None, now=NOW, limits=limits, resolvers=RESOLVERS)

    zone = result.details["zone"]
    assert "error" not in zone
    assert [s["state"] for s in zone["servers"]] == ["ok"] * 8
    assert {s["sig_expires"] for s in zone["servers"]} == {iso_utc(NOW + timedelta(days=10))}
    assert [q[2] for q in world.asked_servers()] == ["SOA", "A"]


def test_a_silent_address_shared_by_name_servers_is_asked_twice_in_all(world):
    world.name_servers = {f"ns{i}.example.test": ("192.0.2.1",) for i in range(1, 5)}
    world.silent.add("192.0.2.1")

    zone = _probe(world).details["zone"]

    assert {s["state"] for s in zone["servers"]} == {"silent"}
    assert world.turns == ["192.0.2.1", "192.0.2.1"]


def test_a_zone_without_name_servers_postpones_the_look(world):
    world.name_servers = {}

    assert _probe(world).details["zone"]["error"] == "no name servers listed"


def test_an_unsigned_zone_reads_no_signatures(world):
    world.signed = False

    zone = _probe(world).details["zone"]

    assert all(q[5] is False for q in world.asked_servers())
    assert all("sig_expires" not in s for s in zone["servers"])


def test_an_ipv6_only_name_is_signed_over_its_aaaa(world):
    _probe(world, _rule((R1, (V6,)), (R2, (V6,))))

    assert {q[2] for q in world.asked_servers() if q[5]} == {"AAAA"}


# --- DNSSEC ---


def test_an_expired_signature_is_critical_and_comes_first(world):
    world.sigs["192.0.2.1"] = (NOW - timedelta(days=14), NOW - timedelta(hours=1))
    world.lame.add("198.51.100.2")

    result = _probe(world)

    assert result.status == "critical"
    assert result.message.startswith(
        f"DNSSEC signature over {HOST} expired {iso_utc(NOW - timedelta(hours=1))} "
        "at name server ns1.example.test; name server ns2.example.net not authoritative"
    )


@pytest.mark.parametrize(
    ("left", "status"), [(timedelta(hours=2), "warning"), (timedelta(hours=3), "ok")]
)
def test_a_signature_in_the_last_five_percent_of_its_window_warns(world, left, status):
    # a two-day window, as online signers use it: 5 % are 2.4 hours
    for address in ("192.0.2.1", "198.51.100.2"):
        world.sigs[address] = (NOW + left - timedelta(days=2), NOW + left)

    result = _probe(world)

    assert result.status == status
    if status == "warning":
        assert result.message == (
            f"DNSSEC signature over {HOST} ends {iso_utc(NOW + left)} at name servers "
            "ns1.example.test, ns2.example.net, not renewed"
        )


def test_the_threshold_is_read_against_the_current_time_between_looks(world):
    # two days, three hours left at the look: ok then, inside the last 2.4 hours later
    for address in ("192.0.2.1", "198.51.100.2"):
        world.sigs[address] = (NOW + timedelta(hours=3, days=-2), NOW + timedelta(hours=3))
    prev = _looked(world)
    world.queries.clear()

    result = _probe(world, prev=prev, now=NOW + timedelta(minutes=50))

    assert result.status == "warning" and result.message.endswith("not renewed")
    assert world.asked_servers() == []


@pytest.mark.parametrize("signer", [None, "other.test"])
def test_a_host_served_without_the_zone_s_signature_warns(world, signer):
    if signer is None:
        del world.sigs["198.51.100.2"]
    else:
        world.signer = signer

    result = _probe(world)

    assert result.status == "warning"
    assert "serving www.example.test unsigned in a signed zone" in result.message


def test_a_stored_state_of_the_wrong_shape_is_looked_at_anew(world):
    result = _probe(world, prev={"zone": {"servers": "x", "next_at": 7}})

    assert result.details["zone"]["checked_at"] == iso_utc(NOW)


# --- the wire ---


class _Wire:
    def __init__(self, raises=None):
        self.raises = raises
        self.sent = []

    def __call__(self, query, where, timeout=None, **kw):
        self.sent.append((query, where, timeout))
        if self.raises:
            raise self.raises
        return dns.message.make_response(query), False


def test_exchange_sets_the_flags_the_caller_asks_for(monkeypatch):
    wire = _Wire()
    monkeypatch.setattr(dns.query, "udp_with_fallback", wire)
    qname = dns.name.from_text(HOST)

    dns_sensor.exchange(R1, qname, "A")
    dns_sensor.exchange("192.0.2.1", qname, "SOA", recursion=False, dnssec=True)
    dns_sensor.exchange(R2, qname, "A", checking_disabled=True)

    plain, authority, unchecked = (q for q, _, _ in wire.sent)
    assert plain.flags & dns.flags.RD and not plain.flags & dns.flags.CD
    assert not plain.ednsflags & dns.flags.DO
    assert not authority.flags & dns.flags.RD and authority.ednsflags & dns.flags.DO
    assert unchecked.flags & dns.flags.CD
    assert [w for _, w, _ in wire.sent] == [R1, "192.0.2.1", R2]
    assert {t for _, _, t in wire.sent} == {resolve.QUERY_LIFETIME_S}


@pytest.mark.parametrize(
    "error", [dns.exception.Timeout(), OSError("unreachable"), ValueError("x")]
)
def test_exchange_without_a_reply_gives_none(monkeypatch, error):
    monkeypatch.setattr(dns.query, "udp_with_fallback", _Wire(error))

    assert dns_sensor.exchange(R1, dns.name.from_text(HOST), "A") is None
