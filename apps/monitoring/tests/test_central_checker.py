# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dispatcher of central checks (R-1224): slot, rule public/internal, sensor, history.

Rule and sensor are stand-ins here; their own tests are test_central_resolve.py
and test_central_tls.py.
"""

from contextlib import contextmanager

import pytest

from app.central import resolve
from app.central.limits import SKIPPED_BUSY_MESSAGE, SKIPPED_SPACING_MESSAGE, RunSkipped
from app.central.resolve import Classification, Reach
from app.central.tls import SensorResult
from app.checkers import central
from app.checkers.central import CentralChecker
from app.checkers.context import CheckContext

HOST = "www.example.test"
SINCE = "2026-11-01T08:00:00Z"
ADDRESSES = ("192.0.2.10", "2001:db8::10")


class _Probe:
    def __init__(self, result=None, raises=None):
        self.calls: list[tuple] = []
        self.result = result or SensorResult(
            "ok",
            "certificate valid until …",
            True,
            {"days_left": 50.0, "lifetime_pct": 50.0},
            {"host": HOST, "address": ADDRESSES[0], "port": 443, "sha256": "ab"},
        )
        self.raises = raises

    def __call__(self, host, addresses, port):
        self.calls.append((host, addresses, port))
        if self.raises:
            raise self.raises
        return self.result


class _Slots:
    def __init__(self, free=True):
        self.free = free
        self.taken = 0

    @contextmanager
    def slot(self):
        self.taken += 1
        yield self.free


@pytest.fixture()
def world(monkeypatch):
    """The rule answers PUBLIC with ADDRESSES unless a test says otherwise."""
    state = {"rule": Classification(Reach.PUBLIC, ADDRESSES), "classified": []}

    def classify(host):
        state["classified"].append(host)
        return state["rule"]

    probe = _Probe()
    slots = _Slots()
    monkeypatch.setattr(resolve, "classify", classify)
    monkeypatch.setitem(central._PROBES, "tls", probe)
    monkeypatch.setattr(central, "LIMITS", slots)
    state.update(probe=probe, slots=slots)
    return state


def _run(config=None, prev=None):
    config = config or {"sensor": "tls", "host": HOST}
    return CentralChecker().run_with_context(config, CheckContext(prev_details=prev))


# --- configuration the dispatcher cannot run ---


@pytest.mark.parametrize(
    "config",
    [
        {"sensor": "smtp", "host": HOST},  # not (yet) a sensor
        {"sensor": ["tls"], "host": HOST},
        {"host": HOST},
        {"sensor": "tls"},
        {"sensor": "tls", "host": ""},
        {"sensor": "tls", "host": 42},
    ],
)
def test_a_config_without_sensor_or_host_is_unknown_and_contacts_nothing(world, config):
    status, message, metrics = _run(config)

    assert (status, metrics) == ("unknown", None)
    assert message.startswith("Unknown sensor or no host: ")
    assert world["classified"] == [] and world["probe"].calls == []


# --- public ---


def test_a_public_host_is_probed_on_the_rule_s_addresses_with_the_sensor_port(world):
    status, message, metrics = _run()

    assert (status, message) == ("ok", "certificate valid until …")
    assert world["probe"].calls == [(HOST, ADDRESSES, 443)]
    details = metrics.pop("_details")
    assert metrics == {"days_left": 50.0, "lifetime_pct": 50.0}
    assert details["addresses"] == list(ADDRESSES)
    assert (details["host"], details["port"], details["sha256"]) == (HOST, 443, "ab")
    assert details["public_since"].endswith("Z")
    assert "notes" not in details


def test_a_configured_port_is_used(world):
    _run({"sensor": "tls", "host": HOST, "port": 8443})

    assert world["probe"].calls == [(HOST, ADDRESSES, 8443)]


def test_public_since_stays_from_the_previous_run_of_the_same_host(world):
    _, _, metrics = _run(prev={"host": HOST, "public_since": SINCE})

    assert metrics["_details"]["public_since"] == SINCE


def test_a_changed_host_starts_its_history_over(world):
    _, _, metrics = _run(prev={"host": "old.example.test", "public_since": SINCE})

    assert metrics["_details"]["public_since"] not in (None, SINCE)


def test_the_sensor_status_passes_through(world):
    world["probe"].result = SensorResult(
        "warning", "certificate due for renewal: …", True, {"days_left": 9.0}, {"host": HOST}
    )

    status, message, _ = _run()

    assert (status, message) == ("warning", "certificate due for renewal: …")


def test_the_rule_s_notes_go_into_the_details(world):
    world["rule"] = Classification(Reach.PUBLIC, ADDRESSES, notes=("resolver 192.0.2.53 silent",))

    _, _, metrics = _run()

    assert metrics["_details"]["notes"] == ["resolver 192.0.2.53 silent"]


# --- public by DNS, but no global address answers (rule 3) ---


def _unreached():
    return SensorResult(
        "critical",
        f"no connection to {HOST} port 443: 192.0.2.10: timed out",
        False,
        details={"host": HOST, "port": 443},
    )


def test_an_unreached_host_without_history_is_left_to_the_agent(world):
    world["probe"].result = _unreached()

    status, message, metrics = _run()

    assert status == "unknown"
    assert message == (
        f"not public – checked by the agent (no connection to {HOST} port 443: 192.0.2.10: timed out)"
    )
    assert "public_since" not in metrics["_details"]


def test_an_unreached_host_that_was_public_is_critical(world):
    world["probe"].result = _unreached()

    status, message, metrics = _run(prev={"host": HOST, "public_since": SINCE})

    assert status == "critical"
    assert message == f"no connection to {HOST} port 443: 192.0.2.10: timed out"
    assert metrics["_details"]["public_since"] == SINCE


# --- not public, resolvers away ---


def test_a_host_that_is_not_public_is_left_to_the_agent_and_not_contacted(world):
    world["rule"] = Classification(Reach.NOT_PUBLIC, notes=("not a global address",))

    status, message, metrics = _run()

    assert status == "unknown"
    assert message == "not public – checked by the agent (not a global address)"
    assert world["probe"].calls == []
    assert metrics == {"_details": {"host": HOST, "port": 443, "notes": ["not a global address"]}}


def test_a_host_that_is_no_longer_public_is_critical_and_not_contacted(world):
    world["rule"] = Classification(Reach.NOT_PUBLIC, notes=("no global address",))

    status, message, metrics = _run(prev={"host": HOST, "public_since": SINCE})

    assert status == "critical"
    assert message == f"{HOST} is no longer public (no global address)"
    assert world["probe"].calls == []
    assert metrics["_details"]["public_since"] == SINCE


def test_unreachable_resolvers_give_no_verdict_and_keep_the_history(world):
    world["rule"] = Classification(
        Reach.RESOLVERS_UNREACHABLE, notes=("resolver 192.0.2.53 silent",)
    )

    status, message, metrics = _run(prev={"host": HOST, "public_since": SINCE})

    assert (status, message) == ("unknown", "public resolvers unreachable")
    assert world["probe"].calls == []
    assert metrics["_details"]["public_since"] == SINCE


# --- limits ---


def test_without_a_free_slot_the_run_is_skipped_before_anything_is_asked(world):
    world["slots"].free = False

    with pytest.raises(RunSkipped, match=SKIPPED_BUSY_MESSAGE):
        _run()

    assert world["classified"] == [] and world["probe"].calls == []


def test_a_skip_from_the_sensor_passes_through(world):
    world["probe"].raises = RunSkipped(SKIPPED_SPACING_MESSAGE)

    with pytest.raises(RunSkipped, match=SKIPPED_SPACING_MESSAGE):
        _run()


def test_run_without_a_context_starts_without_history(world):
    status, _, metrics = CentralChecker().run({"sensor": "tls", "host": HOST})

    assert status == "ok"
    assert metrics["_details"]["public_since"].endswith("Z")
    assert world["slots"].taken == 1
