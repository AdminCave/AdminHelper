# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensor rdap of central checks (R-1224): registration status and expiry of a domain.

The IANA bootstrap and the registries are a stand-in for fetch.get; the HTTPS path
itself is test_central_fetch.py.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.central import fetch, rdap
from app.central.fetch import FetchError, HttpAnswer

NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
HOST = "www.example.test"
NIC = "https://rdap.nic.test/"
SERVICES = [
    [["test"], ["http://rdap.nic.test/", NIC]],
    [["co.test"], ["https://rdap.co.test"]],
]


def _bootstrap(services=None, *, status=200):
    body = {"version": "1.0", "services": SERVICES if services is None else services}
    return HttpAnswer(status, None, json.dumps(body).encode())


_UNSET = object()


def _domain(name, *, status=("active",), expires=None, events=_UNSET):
    """A domain answer; `name` None leaves ldhName out, other values go in as given."""
    body = {"objectClassName": "domain"}
    if name is not None:
        body["ldhName"] = name
    body["status"] = list(status) if isinstance(status, tuple) else status
    if events is _UNSET and expires is not None:
        events = [
            {"eventAction": "registration", "eventDate": "2020-01-01T00:00:00Z"},
            {"eventAction": "expiration", "eventDate": expires},
        ]
    if events is not _UNSET:
        body["events"] = events
    return HttpAnswer(200, None, json.dumps(body).encode())


def _in(days: float) -> str:
    return (NOW + timedelta(days=days)).isoformat().replace("+00:00", "Z")


NOT_FOUND = HttpAnswer(404, None, b'{"errorCode": 404}')
REGISTERED = _domain("example.test", expires=_in(200))


class _Registry:
    """fetch.get stand-in: the IANA bootstrap and the registries' domain answers."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.bootstrap = _bootstrap()
        self.domains = {f"{NIC}domain/example.test": REGISTERED}

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        answer = self.bootstrap if url == rdap.BOOTSTRAP_URL else self.domains.get(url, NOT_FOUND)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def urls(self) -> list[str]:
        return [url for url, _ in self.calls]

    @property
    def asked(self) -> list[str]:
        return [url for url in self.urls if url != rdap.BOOTSTRAP_URL]


@pytest.fixture()
def registry(monkeypatch):
    monkeypatch.setattr(rdap, "_bootstrap", rdap._Bootstrap())
    stand_in = _Registry()
    monkeypatch.setattr(fetch, "get", stand_in)
    return stand_in


def _probe(host=HOST, params=None, prev=None, now=NOW):
    return rdap.probe(host, params or {}, prev, now=now)


def _known(domain="example.test"):
    return {"host": HOST, "rdap": {"domain": domain, "server": NIC, "registered": True}}


# --- finding the registered domain ---


def test_the_host_and_its_parents_are_asked_longest_first_until_the_registry_knows_one(
    registry,
):
    result = _probe("www.shop.example.test")

    assert registry.asked == [
        f"{NIC}domain/www.shop.example.test",
        f"{NIC}domain/shop.example.test",
        f"{NIC}domain/example.test",
    ]
    assert (result.status, result.reached) == ("ok", True)
    assert result.details["rdap"]["domain"] == "example.test"
    assert result.details["rdap"]["server"] == NIC


def test_a_deep_host_asks_the_three_names_nearest_the_top_level_domain(registry):
    _probe("a.b.c.example.test")

    assert registry.asked == [
        f"{NIC}domain/b.c.example.test",
        f"{NIC}domain/c.example.test",
        f"{NIC}domain/example.test",
    ]


def test_the_search_stops_at_the_first_name_the_registry_knows(registry):
    registry.domains[f"{NIC}domain/shop.example.test"] = _domain(
        "shop.example.test", expires=_in(200)
    )

    result = _probe("www.shop.example.test")

    assert registry.asked == [
        f"{NIC}domain/www.shop.example.test",
        f"{NIC}domain/shop.example.test",
    ]
    assert result.details["rdap"]["domain"] == "shop.example.test"


def test_a_later_run_asks_for_the_kept_domain_alone(registry):
    result = _probe(prev=_known())

    assert registry.asked == [f"{NIC}domain/example.test"]
    assert result.status == "ok"


def test_a_kept_domain_the_host_does_not_lie_in_is_ignored(registry):
    _probe(prev=_known("other.test"))

    assert registry.asked == [f"{NIC}domain/{HOST}", f"{NIC}domain/example.test"]


@pytest.mark.parametrize("old", [None, "example.test", ["example.test"], {"domain": 42}])
def test_unusable_previous_details_start_the_search_over(registry, old):
    _probe(prev={"rdap": old})

    assert registry.asked == [f"{NIC}domain/{HOST}", f"{NIC}domain/example.test"]


def test_the_host_is_compared_without_case_and_trailing_dot(registry):
    result = _probe("WWW.Example.TEST.", prev=_known())

    assert registry.asked == [f"{NIC}domain/example.test"]
    assert result.status == "ok"


def test_a_kept_domain_the_registry_no_longer_knows_is_critical(registry):
    del registry.domains[f"{NIC}domain/example.test"]

    result = _probe(prev=_known())

    assert (result.status, result.reached) == ("critical", True)
    assert result.message == "example.test is no longer registered (rdap.nic.test answers 404)"
    assert result.details["rdap"] == {
        "domain": "example.test",
        "server": NIC,
        "registered": False,
        "checked_at": "2026-11-12T12:00:00Z",
    }


def test_no_registration_on_the_first_run_is_unknown(registry):
    registry.domains.clear()

    result = _probe()

    assert (result.status, result.reached) == ("unknown", False)
    assert result.message == f"no registration found for {HOST} or its parent domains"
    assert result.details == {}


def test_a_registered_domain_as_host_names_no_parents(registry):
    registry.domains.clear()

    result = _probe("example.test")

    assert result.message == "no registration found for example.test"


def test_a_top_level_domain_is_unknown_and_asks_nobody(registry):
    result = _probe("test")

    assert (result.status, result.message) == ("unknown", "test is a top-level domain")
    assert registry.calls == []


def test_a_top_level_domain_without_rdap_service_is_unknown(registry):
    result = _probe("www.example.invalid")

    assert (result.status, result.message) == ("unknown", "no RDAP service for .invalid")
    assert registry.asked == []


def test_long_messages_are_capped(registry):
    registry.domains.clear()
    host = ".".join(["a" * 63] * 3) + ".test"

    result = _probe(host)

    assert len(result.message) == rdap.MAX_TEXT


# --- the registry's server ---


def test_the_longest_listed_suffix_names_the_server(registry):
    registry.domains["https://rdap.co.test/domain/example.co.test"] = _domain(
        "example.co.test", expires=_in(200)
    )

    result = _probe("www.example.co.test")

    assert registry.asked == [
        "https://rdap.co.test/domain/www.example.co.test",
        "https://rdap.co.test/domain/example.co.test",
    ]
    assert result.details["rdap"]["server"] == "https://rdap.co.test/"


def test_de_is_asked_at_denic_and_reports_the_status_alone(registry):
    registry.domains["https://rdap.denic.de/domain/example.de"] = _domain(
        "example.de", status=["active"]
    )

    result = _probe("www.example.de")

    assert registry.asked[-1] == "https://rdap.denic.de/domain/example.de"
    assert (result.status, result.reached) == ("ok", True)
    assert result.message == (
        "example.de is registered (status active); the registry publishes no expiry date"
    )
    assert result.metrics == {}
    assert result.details["rdap"]["expires"] is None


def test_a_listed_top_level_domain_wins_over_the_extra_table(registry):
    registry.bootstrap = _bootstrap([[["de"], ["https://rdap.registry.test/"]]])

    _probe("example.de")

    assert registry.asked == ["https://rdap.registry.test/domain/example.de"]


def test_domain_queries_ask_for_rdap_json_and_the_bootstrap_has_its_own_bound(registry):
    _probe()

    by_url = dict(registry.calls)
    assert by_url[rdap.BOOTSTRAP_URL] == {"max_body": rdap.BOOTSTRAP_MAX_BODY}
    assert by_url[f"{NIC}domain/example.test"] == {"accept": "application/rdap+json"}


# --- the verdict ---


@pytest.mark.parametrize(
    ("days", "status", "message"),
    [
        (200, "ok", "example.test expires on 2027-05-31 (in 200 days)"),
        (30, "ok", "example.test expires on 2026-12-12 (in 30 days)"),
        (29.5, "warning", "example.test expires on 2026-12-12 (in 29 days)"),
        (7, "warning", "example.test expires on 2026-11-19 (in 7 days)"),
        (6.9, "critical", "example.test expires on 2026-11-19 (in 6 days)"),
        (1, "critical", "example.test expires on 2026-11-13 (in 1 day)"),
        (0.5, "critical", "example.test expires on 2026-11-13 (within a day)"),
        (-1, "critical", "example.test expired on 2026-11-11"),
    ],
)
def test_the_expiry_date_against_the_default_thresholds(registry, days, status, message):
    registry.domains[f"{NIC}domain/example.test"] = _domain("example.test", expires=_in(days))

    result = _probe(prev=_known())

    assert (result.status, result.message) == (status, message)
    assert result.metrics == {"days_left": round(days, 2)}
    assert result.details["rdap"]["expires"] == _in(days)


@pytest.mark.parametrize(("days", "status"), [(11, "ok"), (5, "warning"), (1.5, "critical")])
def test_own_thresholds_apply(registry, days, status):
    registry.domains[f"{NIC}domain/example.test"] = _domain("example.test", expires=_in(days))

    result = _probe(params={"warn_days": 10, "crit_days": 2}, prev=_known())

    assert result.status == status


@pytest.mark.parametrize(
    "params",
    [
        {"warn_days": "10"},
        {"warn_days": 10, "crit_days": 10},
        {"warn_days": 0},
        {"other": 1},
    ],
)
def test_invalid_params_fall_back_to_the_defaults(registry, params):
    registry.domains[f"{NIC}domain/example.test"] = _domain("example.test", expires=_in(20))

    result = _probe(params=params, prev=_known())

    assert result.status == "warning"


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (["client hold"], "example.test: on hold by the registrar, out of DNS"),
        (["clientHold"], "example.test: on hold by the registrar, out of DNS"),
        (["server-hold"], "example.test: on hold by the registry, out of DNS"),
        (["redemption period"], "example.test: deleted, in the redemption period"),
        (["active", "pending_delete"], "example.test: pending delete"),
        (
            ["client hold", "clientHold", "server hold"],
            "example.test: on hold by the registrar, out of DNS, "
            "on hold by the registry, out of DNS",
        ),
    ],
)
def test_a_status_that_takes_the_domain_out_of_dns_is_critical(registry, status, message):
    registry.domains[f"{NIC}domain/example.test"] = _domain(
        "example.test", status=status, expires=_in(200)
    )

    result = _probe(prev=_known())

    assert (result.status, result.message) == ("critical", message)
    assert result.details["rdap"]["status"] == status


def test_a_hold_is_critical_without_an_expiry_date(registry):
    registry.domains[f"{NIC}domain/example.test"] = _domain("example.test", status=["serverHold"])

    result = _probe(prev=_known())

    assert result.status == "critical"


def test_the_details_carry_what_the_registry_said(registry):
    result = _probe(prev=_known())

    assert result.details == {
        "rdap": {
            "domain": "example.test",
            "server": NIC,
            "registered": True,
            "status": ["active"],
            "expires": _in(200),
            "checked_at": "2026-11-12T12:00:00Z",
        }
    }


def test_a_status_list_is_bounded_and_takes_printable_strings_only(registry):
    status = [42, "line\nbreak", "x" * 100] + [f"s{i}" for i in range(20)]
    registry.domains[f"{NIC}domain/example.test"] = _domain("example.test", status=status)

    result = _probe(prev=_known())

    kept = result.details["rdap"]["status"]
    assert kept[0] == "x" * rdap.MAX_STATUS_TEXT
    assert kept[1:] == [f"s{i}" for i in range(rdap.MAX_STATUS - 1)]


def test_a_status_that_is_no_list_counts_as_none(registry):
    registry.domains[f"{NIC}domain/example.test"] = _domain("example.test", status="active")

    result = _probe(prev=_known())

    assert result.details["rdap"]["status"] == []
    assert "(status none given)" in result.message


@pytest.mark.parametrize(
    "events",
    [
        [
            {"eventAction": "expiration", "eventDate": "2027-01-01T00:00:00"},  # no offset
            {"eventAction": "EXPIRATION", "eventDate": "2027-05-31T12:00:00+00:00"},
        ],
        [
            "not an event",
            {"eventAction": "expiration", "eventDate": "soon"},
            {"eventAction": "expiration", "eventDate": 1800000000},
            {"eventAction": "expiration", "eventDate": "2027-05-31T14:00:00+02:00"},
        ],
    ],
)
def test_the_first_readable_expiration_event_counts(registry, events):
    registry.domains[f"{NIC}domain/example.test"] = _domain("example.test", events=events)

    result = _probe(prev=_known())

    assert result.details["rdap"]["expires"] == "2027-05-31T12:00:00Z"


@pytest.mark.parametrize("events", [None, "expiration", [{"eventAction": "registration"}]])
def test_no_readable_expiration_reports_the_status_alone(registry, events):
    registry.domains[f"{NIC}domain/example.test"] = _domain("example.test", events=events)

    result = _probe(prev=_known())

    assert (result.status, result.metrics) == ("ok", {})
    assert result.message.endswith("the registry publishes no expiry date")


# --- the answer for the name asked ---


def test_an_answer_for_the_domain_that_holds_the_name_is_taken(registry):
    registry.domains[f"{NIC}domain/{HOST}"] = _domain("Example.TEST.", expires=_in(200))

    result = _probe()

    assert registry.asked == [f"{NIC}domain/{HOST}"]
    assert result.details["rdap"]["domain"] == "example.test"
    assert result.message.startswith("example.test expires on")


@pytest.mark.parametrize("ldh", ["other.test", "test", "sub.www.example.test"])
def test_an_answer_for_another_name_is_unknown(registry, ldh):
    registry.domains[f"{NIC}domain/example.test"] = _domain(ldh, expires=_in(200))

    result = _probe(prev=_known())

    assert (result.status, result.reached) == ("unknown", False)
    assert result.message == "RDAP rdap.nic.test: answer for another name"


def test_an_answer_without_a_name_counts_for_the_name_asked(registry):
    registry.domains[f"{NIC}domain/example.test"] = _domain(None, expires=_in(200))

    result = _probe(prev=_known())

    assert result.details["rdap"]["domain"] == "example.test"


@pytest.mark.parametrize("body", [b"<html>", b"[1, 2]", b'"text"', b"[" * 100_000])
def test_an_answer_that_is_no_json_object_is_unknown(registry, body):
    registry.domains[f"{NIC}domain/example.test"] = HttpAnswer(200, None, body)

    result = _probe(prev=_known())

    assert (result.status, result.reached) == ("unknown", False)
    assert result.message == "RDAP rdap.nic.test: no RDAP JSON object"


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (HttpAnswer(429, "60", b""), "RDAP rdap.nic.test: rate limited (HTTP 429)"),
        (HttpAnswer(500, None, b""), "RDAP rdap.nic.test: HTTP 500"),
        (HttpAnswer(301, None, b""), "RDAP rdap.nic.test: HTTP 301"),
        (FetchError("timed out", temporary=True), "RDAP rdap.nic.test: timed out"),
    ],
)
def test_a_registry_without_an_answer_gives_no_verdict(registry, answer, message):
    registry.domains[f"{NIC}domain/example.test"] = answer

    result = _probe(prev=_known())

    assert (result.status, result.message, result.reached) == ("unknown", message, False)


def test_a_failure_on_the_first_run_ends_the_search(registry):
    registry.domains[f"{NIC}domain/{HOST}"] = HttpAnswer(503, None, b"")

    result = _probe()

    assert registry.asked == [f"{NIC}domain/{HOST}"]
    assert result.message == "RDAP rdap.nic.test: HTTP 503"


# --- the IANA bootstrap ---


def test_the_bootstrap_is_fetched_once_a_day(registry):
    _probe(now=NOW)
    _probe(now=NOW + timedelta(hours=23, minutes=59))
    assert registry.urls.count(rdap.BOOTSTRAP_URL) == 1

    _probe(now=NOW + timedelta(days=1))
    assert registry.urls.count(rdap.BOOTSTRAP_URL) == 2


def test_without_a_bootstrap_there_is_no_verdict_and_no_retry_for_15_minutes(registry):
    registry.bootstrap = FetchError("connection refused")

    first = _probe(now=NOW)
    second = _probe(now=NOW + timedelta(minutes=14))

    assert (first.status, first.reached) == ("unknown", False)
    assert first.message == "IANA RDAP bootstrap: connection refused"
    assert second.message == first.message
    assert registry.urls == [rdap.BOOTSTRAP_URL]

    registry.bootstrap = _bootstrap()
    third = _probe(now=NOW + timedelta(minutes=15))
    assert third.status == "ok"
    assert registry.urls.count(rdap.BOOTSTRAP_URL) == 2


def test_an_old_bootstrap_serves_on_while_the_new_one_fails(registry):
    _probe(now=NOW)
    registry.bootstrap = HttpAnswer(503, None, b"")
    later = NOW + timedelta(days=2)

    result = _probe(prev=_known(), now=later)
    _probe(prev=_known(), now=later + timedelta(minutes=10))

    assert result.status == "ok"
    assert registry.urls.count(rdap.BOOTSTRAP_URL) == 2
    assert rdap._bootstrap.error == "HTTP 503"

    registry.bootstrap = _bootstrap()
    _probe(prev=_known(), now=later + timedelta(minutes=15))
    assert registry.urls.count(rdap.BOOTSTRAP_URL) == 3
    assert rdap._bootstrap.fetched_at == later + timedelta(minutes=15)


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (HttpAnswer(500, None, b""), "HTTP 500"),
        (HttpAnswer(200, None, b"<html>"), "unreadable file"),
        (HttpAnswer(200, None, b"[]"), "unreadable file"),
        (HttpAnswer(200, None, b'{"services": [{"a": 1}]}'), "unreadable file"),
        (HttpAnswer(200, None, b'{"services": [["test"]]}'), "unreadable file"),
        (HttpAnswer(200, None, b"[" * 100_000), "unreadable file"),
        (_bootstrap([]), "no https server listed"),
        (_bootstrap([[["test"], ["http://rdap.nic.test/"]]]), "no https server listed"),
    ],
)
def test_an_unusable_bootstrap_is_unknown(registry, answer, message):
    registry.bootstrap = answer

    result = _probe()

    assert (result.status, result.message) == ("unknown", f"IANA RDAP bootstrap: {message}")


def test_the_bootstrap_takes_the_first_https_url_per_entry_with_a_trailing_slash():
    body = _bootstrap(
        [
            [
                ["test", "EXAMPLE.", 42, ""],
                ["http://a.test/", "https://b.test/rdap", "https://c.test/"],
            ],
            [["one"], ["https://with space.test/", "https://" + "x" * 200, "https://d.test/"]],
            ["test-only", ["https://e.test/"]],
            [["two"], "https://f.test/"],
            [["test"], ["https://later.test/"]],
        ]
    ).body

    assert rdap._parse_bootstrap(body) == {
        "test": "https://b.test/rdap/",
        "example": "https://b.test/rdap/",
        "one": "https://d.test/",
    }
