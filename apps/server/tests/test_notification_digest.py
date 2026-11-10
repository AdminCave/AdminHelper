# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1081: quiet hours hold the external channels back, the digest gathers e-mails.

Pinned here: an entry queued in the quiet hours waits for their end and the drain sends
it then; critical passes unless the person turned that off; with the digest on, the
e-mail of info, warning and ok waits for the digest (status digest) while the other
channels and a critical e-mail stay with the drain; the digest goes at 08:00 in the
person's zone, daily or on Mondays, once per window, not without entries, at the next
run once it is turned off, and retries a failed send up to the cutoff."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.config import NOTIFICATION_MAX_ATTEMPTS
from app.modules.notifications import digest as digest_mod
from app.modules.notifications import outbox as outbox_mod
from app.modules.notifications.digest import send_digests
from app.modules.notifications.incidents import ingest
from app.modules.notifications.models import NotificationOutbox, NotificationSettings
from app.modules.notifications.outbox import drain_outbox

from .test_notification_incidents import _admin, _check
from .test_notifications import _server

NTFY = "https://ntfy.example/alerts"


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# 2026-11-05 is a Thursday; Europe/Berlin is UTC+1 then.
QUIET = _utc(2026, 11, 5, 22, 30)  # 23:30 in Berlin, inside 22:00-07:00
QUIET_END = _utc(2026, 11, 6, 6, 0)  # 07:00 in Berlin
DAY = _utc(2026, 11, 5, 10, 0)  # 11:00 in Berlin
NEXT_DIGEST = _utc(2026, 11, 6, 7, 0)  # 08:00 in Berlin
MONDAY_DIGEST = _utc(2026, 11, 9, 7, 0)


@pytest.fixture()
def web01(db_session):
    return _server(db_session, "srv-1", name="web01")


@pytest.fixture()
def wire(monkeypatch):
    """What the drain and the digest sent, as (channel, address, subject, body)."""
    sent: list = []
    monkeypatch.setattr(outbox_mod, "send_email", lambda to, s, b: sent.append(("email", to, s, b)))
    monkeypatch.setattr(
        outbox_mod, "send_ntfy", lambda url, s, b, level: sent.append(("ntfy", url, s, b))
    )
    monkeypatch.setattr(
        digest_mod, "send_email", lambda to, s, b: sent.append(("digest", to, s, b))
    )
    return sent


def _person(db, **settings):
    user = _admin(db)
    values = dict(
        matrix=json.dumps(
            {row: ["email", "ntfy"] for row in ("critical", "warning", "info", "ok")}
        ),
        ntfy_url=NTFY,
        timezone="Europe/Berlin",
    )
    values.update(settings)
    row = db.get(NotificationSettings, user.id)
    if row is None:
        row = NotificationSettings(user_id=user.id)
        db.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    db.commit()
    return user


def _entries(db, user):
    return (
        db.query(NotificationOutbox)
        .filter(NotificationOutbox.user_id == user.id)
        .order_by(NotificationOutbox.id)
        .all()
    )


def _warning(key="check:1"):
    return _check("warning", severity="warning", key=key)


class TestQuietHours:
    def test_a_warning_waits_for_the_end_and_goes_then(self, db_session, web01, wire):
        user = _person(db_session, quiet_enabled=True)
        ingest(db_session, _warning(), now=QUIET)

        entries = _entries(db_session, user)
        assert [(e.channel, e.status, e.next_attempt_at) for e in entries] == [
            ("email", "pending", QUIET_END),
            ("ntfy", "pending", QUIET_END),
        ]
        assert drain_outbox(db_session, now=_utc(2026, 11, 6, 5, 59)) == (0, 0)
        assert wire == []
        assert drain_outbox(db_session, now=QUIET_END) == (2, 0)
        assert [w[0] for w in wire] == ["email", "ntfy"]

    def test_outside_the_quiet_hours_nothing_waits(self, db_session, web01, wire):
        user = _person(db_session, quiet_enabled=True)
        ingest(db_session, _warning(), now=DAY)

        assert [e.next_attempt_at for e in _entries(db_session, user)] == [None, None]

    def test_quiet_hours_off_hold_nothing(self, db_session, web01, wire):
        user = _person(db_session, quiet_enabled=False)
        ingest(db_session, _warning(), now=QUIET)

        assert [e.next_attempt_at for e in _entries(db_session, user)] == [None, None]

    def test_critical_passes_by_default(self, db_session, web01, wire):
        user = _person(db_session, quiet_enabled=True)
        ingest(db_session, _check(), now=QUIET)

        assert [(e.status, e.next_attempt_at) for e in _entries(db_session, user)] == [
            ("pending", None),
            ("pending", None),
        ]
        assert drain_outbox(db_session, now=QUIET) == (2, 0)

    def test_critical_waits_when_it_may_not_pass(self, db_session, web01, wire):
        user = _person(db_session, quiet_enabled=True, quiet_critical=False)
        ingest(db_session, _check(), now=QUIET)

        assert [e.next_attempt_at for e in _entries(db_session, user)] == [QUIET_END] * 2
        assert drain_outbox(db_session, now=QUIET) == (0, 0)

    def test_the_all_clear_waits_too(self, db_session, web01, wire):
        user = _person(db_session, quiet_enabled=True)
        ingest(db_session, _check(), now=DAY)
        ingest(db_session, _check("ok", severity="info"), now=QUIET)

        held = [e for e in _entries(db_session, user) if e.severity == "ok"]
        assert [e.next_attempt_at for e in held] == [QUIET_END] * 2


class TestDigestQueue:
    def test_the_email_of_a_warning_waits_for_the_digest(self, db_session, web01, wire):
        user = _person(db_session, digest="daily")
        ingest(db_session, _warning(), now=DAY)

        assert [(e.channel, e.status) for e in _entries(db_session, user)] == [
            ("email", "digest"),
            ("ntfy", "pending"),
        ]
        assert drain_outbox(db_session, now=DAY) == (1, 0)
        assert [w[0] for w in wire] == ["ntfy"]

    def test_a_critical_email_stays_immediate(self, db_session, web01, wire):
        user = _person(db_session, digest="daily")
        ingest(db_session, _check(), now=DAY)

        assert [e.status for e in _entries(db_session, user)] == ["pending", "pending"]

    def test_a_digest_entry_in_the_quiet_hours_has_no_retry_time(self, db_session, web01, wire):
        user = _person(db_session, digest="daily", quiet_enabled=True)
        ingest(db_session, _warning(), now=QUIET)

        assert [(e.status, e.next_attempt_at) for e in _entries(db_session, user)] == [
            ("digest", None),
            ("pending", QUIET_END),
        ]


class TestSendDigests:
    def test_daily_goes_at_eight_in_the_persons_zone(self, db_session, web01, wire):
        user = _person(db_session, digest="daily")
        ingest(db_session, _warning("check:1"), now=DAY)
        ingest(db_session, _warning("check:2"), now=_utc(2026, 11, 5, 12, 5))
        wire.clear()

        assert send_digests(db_session, _utc(2026, 11, 6, 6, 59)) == (0, 0)
        assert send_digests(db_session, NEXT_DIGEST) == (1, 0)

        assert len(wire) == 1
        kind, to, subject, body = wire[0]
        assert (kind, to) == ("digest", "boss@example.org")
        assert subject == "AdminHelper digest: 2 notifications"
        assert body.splitlines() == [
            "2026-11-05 11:00 [warning] CPU warning on web01",
            "2026-11-05 13:05 [warning] CPU warning on web01",
        ]
        mails = [e for e in _entries(db_session, user) if e.channel == "email"]
        assert [(e.status, e.sent_at, e.attempts) for e in mails] == [("sent", NEXT_DIGEST, 1)] * 2
        db_session.refresh(db_session.get(NotificationSettings, user.id))
        assert db_session.get(NotificationSettings, user.id).digest_last_at == NEXT_DIGEST

    def test_once_per_window(self, db_session, web01, wire):
        _person(db_session, digest="daily")
        ingest(db_session, _warning("check:1"), now=DAY)
        assert send_digests(db_session, NEXT_DIGEST) == (1, 0)
        # Queued after the digest of this morning: it waits for tomorrow's.
        ingest(db_session, _warning("check:2"), now=_utc(2026, 11, 6, 7, 10))
        wire.clear()

        assert send_digests(db_session, _utc(2026, 11, 6, 7, 15)) == (0, 0)
        assert send_digests(db_session, _utc(2026, 11, 7, 6, 59)) == (0, 0)
        assert send_digests(db_session, _utc(2026, 11, 7, 7, 0)) == (1, 0)
        assert [w[2] for w in wire] == ["AdminHelper digest: 1 notification"]

    def test_an_entry_older_than_the_last_digest_waits_for_the_next(self, db_session, web01, wire):
        # A ping whose transaction began before the digest ran but committed after it
        # carries a created_at inside the window that was just sent.
        user = _person(db_session, digest="daily")
        ingest(db_session, _warning("check:1"), now=DAY)
        assert send_digests(db_session, NEXT_DIGEST) == (1, 0)
        ingest(db_session, _warning("check:2"), now=_utc(2026, 11, 6, 6, 30))
        wire.clear()

        assert send_digests(db_session, _utc(2026, 11, 6, 7, 5)) == (0, 0)
        assert send_digests(db_session, _utc(2026, 11, 7, 7, 0)) == (1, 0)
        assert db_session.get(NotificationSettings, user.id).digest_last_at == _utc(
            2026, 11, 7, 7, 0
        )

    def test_a_late_run_still_sends_once(self, db_session, web01, wire):
        _person(db_session, digest="daily")
        ingest(db_session, _warning(), now=DAY)
        wire.clear()

        assert send_digests(db_session, _utc(2026, 11, 6, 9, 0)) == (1, 0)
        assert send_digests(db_session, _utc(2026, 11, 6, 9, 5)) == (0, 0)
        assert len(wire) == 1

    def test_weekly_goes_on_monday(self, db_session, web01, wire):
        _person(db_session, digest="weekly")
        ingest(db_session, _warning(), now=DAY)
        wire.clear()

        assert send_digests(db_session, NEXT_DIGEST) == (0, 0)
        assert send_digests(db_session, _utc(2026, 11, 8, 7, 0)) == (0, 0)
        assert send_digests(db_session, MONDAY_DIGEST) == (1, 0)

    def test_no_mail_without_entries(self, db_session, web01, wire):
        _person(db_session, digest="daily")

        assert send_digests(db_session, NEXT_DIGEST) == (0, 0)
        assert wire == []

    def test_turned_off_the_waiting_entries_go_at_the_next_run(self, db_session, web01, wire):
        user = _person(db_session, digest="daily")
        ingest(db_session, _warning(), now=DAY)
        settings = db_session.get(NotificationSettings, user.id)
        settings.digest = "off"
        db_session.commit()
        wire.clear()

        assert send_digests(db_session, _utc(2026, 11, 5, 10, 5)) == (1, 0)
        assert [w[0] for w in wire] == ["digest"]

    def test_a_failed_send_retries_up_to_the_cutoff(self, db_session, web01, monkeypatch):
        def boom(*_):
            raise RuntimeError("relay down")

        monkeypatch.setattr(digest_mod, "send_email", boom)
        user = _person(db_session, digest="daily", matrix=json.dumps({"warning": ["email"]}))
        ingest(db_session, _warning(), now=DAY)

        for attempt in range(1, NOTIFICATION_MAX_ATTEMPTS):
            assert send_digests(db_session, NEXT_DIGEST) == (0, 0)
            (entry,) = _entries(db_session, user)
            assert (entry.status, entry.attempts, entry.last_error) == (
                "digest",
                attempt,
                "relay down",
            )
        assert send_digests(db_session, NEXT_DIGEST) == (0, 1)
        (entry,) = _entries(db_session, user)
        assert entry.status == "failed"
        assert db_session.get(NotificationSettings, user.id).digest_last_at is None


def test_a_digest_mail_lists_at_most_its_cap_and_counts_the_rest(monkeypatch):
    # R-1188: a long wait must not make one unbounded mail; every entry still counts
    # as sent, the bell lists them all.
    mails: list = []
    monkeypatch.setattr(digest_mod, "send_email", lambda to, s, b: mails.append((to, s, b)))
    cap = digest_mod.DIGEST_MAX_LINES
    entries = [
        SimpleNamespace(
            created_at=DAY,
            severity="warning",
            title=f"entry {n}",
            address="boss@example.org",
            attempts=0,
            status="digest",
            sent_at=None,
            last_error=None,
            user_id=1,
        )
        for n in range(cap + 1)
    ]

    assert digest_mod._send(None, entries, NEXT_DIGEST) == (True, 0)

    ((to, subject, body),) = mails
    lines = body.split("\n")
    assert (to, subject) == ("boss@example.org", f"AdminHelper digest: {cap + 1} notifications")
    assert len(lines) == cap + 1
    assert lines[0].endswith("entry 0") and lines[cap - 1].endswith(f"entry {cap - 1}")
    assert lines[-1] == "... and 1 more"
    assert {(e.status, e.sent_at) for e in entries} == {("sent", NEXT_DIGEST)}


def test_a_digest_mail_at_its_cap_has_no_closing_line(monkeypatch):
    mails: list = []
    monkeypatch.setattr(digest_mod, "send_email", lambda to, s, b: mails.append(b))
    cap = digest_mod.DIGEST_MAX_LINES
    entries = [
        SimpleNamespace(
            created_at=DAY,
            severity=None,
            title=f"entry {n}",
            address="boss@example.org",
            attempts=0,
            status="digest",
            sent_at=None,
            last_error=None,
            user_id=1,
        )
        for n in range(cap)
    ]

    digest_mod._send(None, entries, NEXT_DIGEST)

    (body,) = mails
    assert len(body.split("\n")) == cap
    assert "more" not in body.split("\n")[-1]
