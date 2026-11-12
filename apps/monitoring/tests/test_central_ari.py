# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ACME Renewal Information for the sensor tls (R-1224, RFC 9773).

The CA is a stand-in for fetch.get; the HTTPS path itself is test_central_fetch.py.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.central import ari, fetch
from app.central.fetch import FetchError, HttpAnswer

NOW = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
DIRECTORY = "https://acme-v02.api.letsencrypt.org/directory"
RENEWAL = "https://acme-v02.api.letsencrypt.org/acme/renewal-info"
KEY = ec.generate_private_key(ec.SECP256R1())


def _cert(org="Let's Encrypt", *, serial=0x87654321, key_id=b"\x01" * 20):
    issuer = [x509.NameAttribute(NameOID.COMMON_NAME, "E7")]
    if org:
        issuer.insert(0, x509.NameAttribute(NameOID.ORGANIZATION_NAME, org))
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "leaf")]))
        .issuer_name(x509.Name(issuer))
        .public_key(KEY.public_key())
        .serial_number(serial)
        .not_valid_before(NOW - timedelta(days=30))
        .not_valid_after(NOW + timedelta(days=60))
    )
    if key_id is not None:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier(key_id, None, None), critical=False
        )
    return builder.sign(KEY, hashes.SHA256())


def _window(start, end, *, url=None, retry=None, status=200):
    body = {"suggestedWindow": {"start": start, "end": end}}
    if url is not None:
        body["explanationURL"] = url
    return HttpAnswer(status, retry, json.dumps(body).encode())


RUNNING = _window("2026-02-28T00:00:00Z", "2026-03-03T00:00:00Z")
PASSED = _window("2026-02-20T00:00:00Z", "2026-02-21T00:00:00Z")


class _Ca:
    """fetch.get stand-in: the directory and one renewalInfo answer (or error)."""

    def __init__(self, renewal=RUNNING):
        self.calls: list[str] = []
        self.directory = HttpAnswer(200, None, json.dumps({"renewalInfo": RENEWAL}).encode())
        self.renewal = renewal

    def __call__(self, url, *, accept="application/json"):
        self.calls.append(url)
        answer = self.directory if url == DIRECTORY else self.renewal
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(ari, "_directories", {})
    monkeypatch.setattr(ari, "_states", {})


@pytest.fixture()
def ca(monkeypatch):
    stand_in = _Ca()
    monkeypatch.setattr(fetch, "get", stand_in)
    return stand_in


def _at(delta: timedelta) -> str:
    return (NOW + delta).isoformat().replace("+00:00", "Z")


# --- CertID and the CA table ---


def test_the_cert_id_matches_the_rfc_example():
    # RFC 9773 §4.1: keyIdentifier 69:88:5B:…:C8:D4 and serial 0x87654321.
    key_id = bytes.fromhex("69885B6B87464041E1B37B847BA0AE2CDE01C8D4")

    assert ari.cert_id(_cert(key_id=key_id)) == "aYhba4dGQEHhs3uEe6CuLN4ByNQ.AIdlQyE"


def test_a_serial_without_the_top_bit_gets_no_leading_zero():
    assert ari.cert_id(_cert(serial=0x01)).endswith(".AQ")


def test_without_an_authority_key_identifier_there_is_no_cert_id(ca):
    leaf = _cert(key_id=None)

    assert ari.cert_id(leaf) is None
    assert ari.evaluate(leaf, None, NOW) == (None, None)
    assert ca.calls == []


@pytest.mark.parametrize(
    ("org", "name"),
    [
        ("Let's Encrypt", "Let's Encrypt"),
        ("Google Trust Services", "Google Trust Services"),
        ("ZeroSSL GmbH", "ZeroSSL"),
        ("Example CA", None),
        (None, None),
    ],
)
def test_the_ca_is_known_by_the_issuer_organisation(org, name):
    found = ari.known_ca(_cert(org))

    assert (found.name if found else None) == name


def test_an_unknown_ca_is_not_asked(ca):
    assert ari.evaluate(_cert("Example CA"), None, NOW) == (None, None)
    assert ca.calls == []


# --- the window ---


def test_a_running_window_is_no_warning(ca):
    leaf = _cert()

    state, warning = ari.evaluate(leaf, None, NOW)

    assert warning is None
    assert ca.calls == [DIRECTORY, f"{RENEWAL}/{ari.cert_id(leaf)}"]
    assert state == {
        "cert_id": ari.cert_id(leaf),
        "checked_at": _at(timedelta(0)),
        "window_start": "2026-02-28T00:00:00Z",
        "window_end": "2026-03-03T00:00:00Z",
        "next_at": _at(ari.LONG_TERM_WAIT),
    }


def test_a_window_wholly_in_the_past_is_a_warning_with_the_explanation(ca):
    ca.renewal = _window(
        "2026-02-20T00:00:00Z", "2026-02-21T00:00:00Z", url="https://ca.example.test/incident"
    )

    state, warning = ari.evaluate(_cert(), None, NOW)

    assert warning == (
        "Let's Encrypt suggests renewal: window 2026-02-20T00:00:00Z to "
        "2026-02-21T00:00:00Z has passed (https://ca.example.test/incident)"
    )
    assert state["explanation_url"] == "https://ca.example.test/incident"


def test_a_window_ending_now_has_passed(ca):
    ca.renewal = _window("2026-03-01T00:00:00Z", "2026-03-01T12:00:00Z")

    assert ari.evaluate(_cert(), None, NOW)[1] is not None


def test_offsets_are_read_as_utc(ca):
    ca.renewal = _window("2026-03-01T10:00:00+02:00", "2026-03-01T13:30:00+01:00")

    state, warning = ari.evaluate(_cert(), None, NOW)

    assert (state["window_start"], state["window_end"]) == (
        "2026-03-01T08:00:00Z",
        "2026-03-01T12:30:00Z",
    )
    assert warning is None


@pytest.mark.parametrize(
    "url",
    [
        "http://ca.example.test/incident",
        "https://ca.example.test/" + "x" * 200,
        "https://ca.example.test/a b",
        "https://ca.example.test/\x1b[31m",
        42,
    ],
)
def test_an_explanation_url_must_be_a_short_plain_https_url(ca, url):
    ca.renewal = _window("2026-02-20T00:00:00Z", "2026-02-21T00:00:00Z", url=url)

    state, warning = ari.evaluate(_cert(), None, NOW)

    assert "explanation_url" not in state
    assert warning.endswith("has passed")


# --- when to ask ---


def test_a_state_that_is_not_due_is_used_without_asking(ca):
    leaf = _cert()
    prev = {
        "cert_id": ari.cert_id(leaf),
        "checked_at": _at(-timedelta(hours=1)),
        "window_start": "2026-02-20T00:00:00Z",
        "window_end": "2026-02-21T00:00:00Z",
        "next_at": _at(timedelta(hours=5)),
    }

    state, warning = ari.evaluate(leaf, prev, NOW)

    assert ca.calls == []
    assert state == prev and warning is not None


def test_a_due_state_is_asked_again_without_the_directory(ca):
    leaf = _cert()
    state, _ = ari.evaluate(leaf, None, NOW)
    ca.calls.clear()

    ari.evaluate(leaf, state, NOW + ari.LONG_TERM_WAIT)

    assert ca.calls == [f"{RENEWAL}/{ari.cert_id(leaf)}"]


def test_the_state_of_another_certificate_is_not_used(ca):
    prev = {"cert_id": "other", "next_at": _at(timedelta(hours=5)), "window_end": "x"}

    state, _ = ari.evaluate(_cert(), prev, NOW)

    assert len(ca.calls) == 2 and state["cert_id"] != "other"


def test_checks_sharing_a_certificate_ask_once(ca):
    leaf = _cert()

    first, _ = ari.evaluate(leaf, None, NOW)
    second, _ = ari.evaluate(leaf, None, NOW + timedelta(hours=1))

    assert ca.calls == [DIRECTORY, f"{RENEWAL}/{ari.cert_id(leaf)}"]
    assert second == first


def test_the_newer_shared_state_wins_over_the_check_s_own(ca):
    leaf = _cert()
    own = {"cert_id": ari.cert_id(leaf), "checked_at": _at(-timedelta(days=2)), "next_at": "x"}
    shared, _ = ari.evaluate(leaf, None, NOW)
    ca.calls.clear()

    state, _ = ari.evaluate(leaf, own, NOW + timedelta(hours=1))

    assert ca.calls == [] and state == shared


def test_the_shared_states_are_bounded(ca, monkeypatch):
    monkeypatch.setattr(ari, "MAX_REMEMBERED", 2)
    leaves = [_cert(serial=s) for s in (1, 2, 3)]

    for leaf in leaves:
        ari.evaluate(leaf, None, NOW)

    assert list(ari._states) == [ari.cert_id(leaves[1]), ari.cert_id(leaves[2])]


def test_the_directory_is_read_once_a_day(ca):
    ari.evaluate(_cert(serial=1), None, NOW)
    ari.evaluate(_cert(serial=2), None, NOW + timedelta(hours=23))
    ari.evaluate(_cert(serial=3), None, NOW + timedelta(days=1))

    assert ca.calls.count(DIRECTORY) == 2


@pytest.mark.parametrize(
    ("retry", "wait"),
    [
        ("21600", timedelta(hours=6)),
        ("3600", timedelta(hours=1)),
        ("10", ari.RETRY_MIN),
        ("999999", ari.RETRY_MAX),
        ("9" * 4000, ari.RETRY_MAX),
        ("Sun, 01 Mar 2026 14:00:00 GMT", timedelta(hours=2)),
        ("Sun, 01 Mar 2026 11:00:00 GMT", ari.RETRY_MIN),  # in the past
        ("soon", ari.LONG_TERM_WAIT),
        ("-5", ari.LONG_TERM_WAIT),
    ],
)
def test_retry_after_sets_the_next_query_within_a_minute_and_a_day(ca, retry, wait):
    ca.renewal = _window("2026-02-28T00:00:00Z", "2026-03-03T00:00:00Z", retry=retry)

    state, _ = ari.evaluate(_cert(), None, NOW)

    assert state["next_at"] == _at(wait)


# --- errors ---


def test_temporary_errors_back_off_three_times_then_wait_six_hours(ca):
    leaf = _cert()
    ca.renewal = HttpAnswer(503, None, b"")
    state, now, waits = None, NOW, []

    for _ in range(4):
        state, warning = ari.evaluate(leaf, state, now)
        due = datetime.fromisoformat(state["next_at"])
        waits.append(due - now)
        now = due

    assert waits == [
        timedelta(minutes=15),
        timedelta(minutes=30),
        timedelta(hours=1),
        ari.LONG_TERM_WAIT,
    ]
    assert (state["error"], state["failures"], warning) == ("renewalInfo: HTTP 503", 4, None)


def test_a_temporary_error_honours_retry_after(ca):
    ca.renewal = HttpAnswer(503, "120", b"")

    state, _ = ari.evaluate(_cert(), None, NOW)

    assert state["next_at"] == _at(timedelta(minutes=2))


@pytest.mark.parametrize(
    ("renewal", "error", "temporary"),
    [
        (HttpAnswer(404, None, b""), "renewalInfo: HTTP 404", False),
        (FetchError("ca.example.test: no global address (x)"), "ca.example.test", False),
        (FetchError("192.0.2.1: timed out", temporary=True), "192.0.2.1: timed out", True),
    ],
)
def test_errors_are_kept_in_the_state(ca, renewal, error, temporary):
    ca.renewal = renewal

    state, warning = ari.evaluate(_cert(), None, NOW)

    assert state["error"].startswith(error) and warning is None
    assert state["next_at"] == _at(ari.BACKOFF_FIRST if temporary else ari.LONG_TERM_WAIT)
    assert ("failures" in state) is temporary


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'{"suggestedWindow": {"start": "2026-03-02T00:00:00Z"}}',
        # the end must come after the start (§4.2)
        b'{"suggestedWindow": {"start": "2026-03-02T00:00:00Z", "end": "2026-03-02T00:00:00Z"}}',
        b'{"suggestedWindow": {"start": "2026-03-02T00:00:00", "end": "2026-03-03T00:00:00"}}',
        # in UTC past the year 9999
        b'{"suggestedWindow": {"start": "9999-12-31T23:59:59-23:59", '
        b'"end": "2026-03-03T00:00:00Z"}}',
    ],
)
def test_an_invalid_answer_keeps_the_last_window(ca, body):
    leaf = _cert()
    state, _ = ari.evaluate(leaf, None, NOW)
    ca.renewal = HttpAnswer(200, None, body)

    later = NOW + ari.LONG_TERM_WAIT
    state, _ = ari.evaluate(leaf, state, later)

    assert state["error"] == "renewalInfo: invalid answer"
    assert state["window_end"] == "2026-03-03T00:00:00Z"
    assert datetime.fromisoformat(state["next_at"]) == later + ari.LONG_TERM_WAIT


def test_a_success_clears_the_error(ca):
    leaf = _cert()
    ca.renewal = HttpAnswer(503, None, b"")
    state, _ = ari.evaluate(leaf, None, NOW)
    ca.renewal = RUNNING

    state, _ = ari.evaluate(leaf, state, NOW + ari.BACKOFF_FIRST)

    assert "error" not in state and "failures" not in state


@pytest.mark.parametrize(
    ("directory", "error", "temporary"),
    [
        (HttpAnswer(200, None, b'{"newOrder": "https://x"}'), "names no renewalInfo", False),
        (HttpAnswer(200, None, b'{"renewalInfo": "http://x"}'), "names no renewalInfo", False),
        (HttpAnswer(200, None, b"<html>"), "names no renewalInfo", False),
        (HttpAnswer(500, None, b""), "ACME directory: HTTP 500", True),
    ],
)
def test_a_directory_without_renewal_info_is_an_error(ca, directory, error, temporary):
    ca.directory = directory

    state, _ = ari.evaluate(_cert(), None, NOW)

    assert error in state["error"]
    assert ("failures" in state) is temporary
    assert ari._directories == {}
