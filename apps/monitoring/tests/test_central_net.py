# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Global addresses and target restraint of the central checks (R-1224).

The address rows are the IANA special-purpose registries as fetched on 2026-11-12,
one case per row, first and last address of the block: a wrong prefix length shows
at one of the two ends.
"""

import ipaddress

import pytest

from app.central import limits
from app.central.limits import Limits
from app.central.net import effective_address, is_global_address

# (block, globally reachable). Deprecated and "N/A" rows count as not global: a
# central check has no business with a relay or a tunnel prefix.
IANA_ROWS = [
    ("0.0.0.0/8", False),
    ("0.0.0.0/32", False),
    ("10.0.0.0/8", False),
    ("100.64.0.0/10", False),
    ("127.0.0.0/8", False),
    ("169.254.0.0/16", False),
    ("172.16.0.0/12", False),
    ("192.0.0.0/24", False),
    ("192.0.0.0/29", False),
    ("192.0.0.8/32", False),
    ("192.0.0.9/32", True),
    ("192.0.0.10/32", True),
    ("192.0.0.170/32", False),
    ("192.0.0.171/32", False),
    ("192.0.2.0/24", False),
    ("192.31.196.0/24", True),
    ("192.52.193.0/24", True),
    ("192.88.99.0/24", False),  # deprecated; ipaddress (3.13, 3.14) says global
    ("192.88.99.2/32", False),  # ipaddress says global
    ("192.168.0.0/16", False),
    ("192.175.48.0/24", True),
    ("198.18.0.0/15", False),
    ("198.51.100.0/24", False),
    ("203.0.113.0/24", False),
    ("240.0.0.0/4", False),
    ("255.255.255.255/32", False),
    ("::1/128", False),
    ("::/128", False),
    ("64:ff9b:1::/48", False),
    ("100::/64", False),
    ("100:0:0:1::/64", False),  # ipaddress says global
    ("2001::/23", False),
    ("2001::/32", False),  # Teredo, "N/A"
    ("2001:1::1/128", True),
    ("2001:1::2/128", True),
    ("2001:1::3/128", True),  # ipaddress says not global
    ("2001:2::/48", False),
    ("2001:3::/32", True),
    ("2001:4:112::/48", True),
    ("2001:10::/28", False),  # deprecated
    ("2001:20::/28", True),
    ("2001:30::/28", True),
    ("2001:db8::/32", False),
    ("2620:4f:8000::/48", True),
    ("3fff::/20", False),
    ("5f00::/16", False),  # ipaddress says global
    ("fc00::/7", False),
    ("fe80::/10", False),
]


@pytest.mark.parametrize(("block", "expected"), IANA_ROWS, ids=[b for b, _ in IANA_ROWS])
def test_iana_row(monkeypatch, block, expected):
    # A listed row is answered by the pinned rows alone, never by Python's own copy of
    # the registries: only then is the answer the same on every Python.
    def consulted(self):
        raise AssertionError(f"ipaddress.is_global consulted for {self}")

    for cls in (ipaddress.IPv4Address, ipaddress.IPv6Address):
        monkeypatch.setattr(cls, "is_global", property(consulted))
    net = ipaddress.ip_network(block)
    assert is_global_address(net.network_address) is expected
    assert is_global_address(net[-1]) is expected


# The rows IANA decides by the embedded IPv4 address (::ffff:0:0/96 "False",
# 64:ff9b::/96 "True", 2002::/16 "N/A"): here that address decides, so the answer
# is the one for the IPv4 host the connection really reaches.
@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("::ffff:192.31.196.1", True),
        ("::ffff:192.0.2.1", False),
        ("64:ff9b::192.31.196.1", True),
        ("64:ff9b::192.0.2.1", False),
        ("2002:c01f:c401::", True),  # 6to4 of 192.31.196.1
        ("2002:c000:201::", False),  # 6to4 of 192.0.2.1
        # The local-use NAT64 prefix is a row of its own and never global.
        ("64:ff9b:1::c01f:c401", False),
    ],
)
def test_embedded_ipv4_decides(address, expected):
    assert is_global_address(ipaddress.ip_address(address)) is expected


@pytest.mark.parametrize(
    "address",
    ["224.0.0.1", "239.255.255.250", "ff02::1", "ff0e::1", "fec0::1"],
)
def test_multicast_and_site_local_are_not_global(address):
    assert is_global_address(ipaddress.ip_address(address)) is False


@pytest.mark.parametrize(
    "address",
    [
        "::7f00:1",  # IPv4-compatible 127.0.0.1, ipaddress says global
        "::a00:1",  # IPv4-compatible 10.0.0.1, ipaddress says global
        "::ffff:0:a00:1",  # IPv4-translated (RFC 2765), not unwrapped
        "400::1",
        "4000::1",  # ipaddress says global
        "8000::1",  # ipaddress says global
        "e000::1",
    ],
)
def test_ipv6_outside_global_unicast_is_not_global(monkeypatch, address):
    # Decided by the 2000::/3 rule alone, whatever Python's copy of the registries says.
    def consulted(self):
        raise AssertionError(f"ipaddress.is_global consulted for {self}")

    monkeypatch.setattr(ipaddress.IPv6Address, "is_global", property(consulted))
    assert is_global_address(ipaddress.ip_address(address)) is False


@pytest.mark.parametrize("address", ["9.9.9.9", "1.1.1.1", "2620:fe::fe"])
def test_ordinary_public_address_is_global(address):
    assert is_global_address(ipaddress.ip_address(address)) is True


@pytest.mark.parametrize(
    ("address", "effective"),
    [
        ("::ffff:192.0.2.1", "192.0.2.1"),
        ("64:ff9b::c000:201", "192.0.2.1"),
        ("2002:c000:201::1", "192.0.2.1"),
        ("2001:db8::1", "2001:db8::1"),
        ("192.0.2.1", "192.0.2.1"),
    ],
)
def test_effective_address(address, effective):
    assert effective_address(ipaddress.ip_address(address)) == ipaddress.ip_address(effective)


# ---- restraint toward the targets -------------------------------------------


class FakeTime:
    """A clock that moves only when told to; `sleep` records and, if asked, moves it."""

    def __init__(self, *, sleep_moves_clock: bool) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []
        self._moves = sleep_moves_clock

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if self._moves:
            self.now += seconds


def _limits(fake: FakeTime, **kwargs) -> Limits:
    return Limits(clock=fake.clock, sleep=fake.sleep, **kwargs)


def test_first_contact_does_not_wait():
    fake = FakeTime(sleep_moves_clock=True)
    assert _limits(fake).address_turn("192.0.2.1") is True
    assert fake.sleeps == []


def test_second_contact_waits_for_the_spacing():
    fake = FakeTime(sleep_moves_clock=True)
    lim = _limits(fake)
    lim.address_turn("192.0.2.1")
    assert lim.address_turn("192.0.2.1") is True
    assert fake.sleeps == [limits.ADDRESS_SPACING_S]


def test_queued_runs_get_successive_starts_and_the_one_too_far_out_is_skipped():
    # The clock stands still, as for runs that all arrive in the same instant: each
    # one reserves the next start, so they go one after the other.
    fake = FakeTime(sleep_moves_clock=False)
    lim = _limits(fake)
    turns = [lim.address_turn("192.0.2.1") for _ in range(7)]
    assert turns == [True] * 6 + [False]
    assert fake.sleeps == [2.0, 4.0, 6.0, 8.0, 10.0]
    assert limits.ADDRESS_SPACING_S == 2.0 and limits.SPACING_WAIT_S == 10.0


def test_spacing_is_per_address():
    fake = FakeTime(sleep_moves_clock=False)
    lim = _limits(fake)
    assert lim.address_turn("192.0.2.1") is True
    assert lim.address_turn("192.0.2.2") is True
    assert fake.sleeps == []


def test_spacing_ends_once_the_reserved_start_has_passed():
    fake = FakeTime(sleep_moves_clock=False)
    lim = _limits(fake)
    lim.address_turn("192.0.2.1")
    fake.now += limits.ADDRESS_SPACING_S
    assert lim.address_turn("192.0.2.2") is True
    # The entry of the first address held nothing back any more and is gone.
    assert set(lim._next_start) == {"192.0.2.2"}
    assert lim.address_turn("192.0.2.1") is True
    assert fake.sleeps == []


def test_mail_spacing_per_address_and_port_with_slack():
    fake = FakeTime(sleep_moves_clock=False)
    lim = _limits(fake)
    assert lim.mail_turn("192.0.2.1", 25) is True
    fake.now += 60
    assert lim.mail_turn("192.0.2.1", 25) is False
    assert lim.mail_turn("192.0.2.1", 587) is True
    assert lim.mail_turn("192.0.2.2", 25) is True
    # A skipped run is no connection: the spacing still counts from the first one.
    fake.now = 1000.0 + limits.MAIL_SPACING_S - limits.MAIL_SPACING_SLACK_S - 0.1
    assert lim.mail_turn("192.0.2.1", 25) is False
    fake.now = 1000.0 + limits.MAIL_SPACING_S - limits.MAIL_SPACING_SLACK_S
    assert lim.mail_turn("192.0.2.1", 25) is True
    assert limits.MAIL_SPACING_S == 900.0
    assert fake.sleeps == []


def test_mail_entries_are_pruned_after_the_spacing():
    fake = FakeTime(sleep_moves_clock=False)
    lim = _limits(fake)
    lim.mail_turn("192.0.2.1", 25)
    fake.now += limits.MAIL_SPACING_S
    lim.mail_turn("192.0.2.2", 143)
    assert set(lim._last_mail) == {("192.0.2.2", 143)}


def test_slot_refuses_when_all_are_taken_and_frees_on_exit():
    # timeout=0: the refusal itself is under test, not the length of the wait.
    lim = Limits(max_parallel=1)
    with lim.slot(timeout=0) as first:
        assert first is True
        with lim.slot(timeout=0) as second:
            assert second is False
    # A refused slot released nothing (the bounded semaphore would raise), and the
    # taken one is free again.
    with lim.slot(timeout=0) as again:
        assert again is True


def test_default_parallelism():
    assert limits.MAX_PARALLEL == 4
    lim = Limits()
    with lim.slot(0) as a, lim.slot(0) as b, lim.slot(0) as c, lim.slot(0) as d:
        assert (a, b, c, d) == (True, True, True, True)
        with lim.slot(0) as e:
            assert e is False
