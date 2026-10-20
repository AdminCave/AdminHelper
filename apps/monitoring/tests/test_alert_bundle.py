# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bundled alert (R-0424 T11, T12): send_bundle reports claimed agent heartbeats
on each channel on its own, one message from BUNDLE_MIN members on, single
messages below; flush_agent_alerts collects the open heartbeats, bundles BUNDLE_MIN
or more and lets fewer wait BUNDLE_WINDOW before they go out on their own. Real
SQLite session; mail is captured at _send_email, the webhook and the hub at
httpx.post."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import alert_bundle, alerter
from app.alert_bundle import (
    BACK,
    BUNDLE_MIN,
    BUNDLE_WINDOW,
    HUB_MAX_IDS,
    SILENT,
    flush_agent_alerts,
    send_bundle,
)
from app.core import database
from app.core.ssrf import UrlVerdict
from app.models import (
    Base,
    MonitorAlertLog,
    MonitorAlertRule,
    MonitorCheck,
    MonitorMaintenance,
    MonitorState,
    MonitorTemplate,
    MonitorTemplateAssignment,
)

_NOW = datetime(2026, 10, 20, 12, 0)
_SHOWN = _NOW - timedelta(hours=1)
_HUB = "http://hub:8080/api/internal/events"
_DOWN = "Agent unreachable for 16 min (limit: 15 min)"
_UP = "Agent active (last report 12s ago)"
_SINGLE_DOWN = "[AdminHelper Monitor] CRITICAL: Agent Heartbeat"


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    # The rule cooldown (_is_in_cooldown) reads the alerter's clock.
    monkeypatch.setattr(alerter, "utcnow_naive", lambda: _NOW)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def channels(monkeypatch):
    """What each channel sent: mails as (check id, msg), webhook bodies, hub
    events. The hub answers with the next of hub_codes, then with hub_code; every
    hub POST leaves "post" in timeline."""
    out = SimpleNamespace(mails=[], webhooks=[], events=[], hub_code=202, hub_codes=[], timeline=[])

    def fake_email(config, rule, check, msg):
        out.mails.append((check.id, msg))
        return True, None

    def fake_post(url, **kwargs):
        if url == _HUB:
            out.events.append(kwargs["json"])
            out.timeline.append("post")
            code = out.hub_codes.pop(0) if out.hub_codes else out.hub_code
            return SimpleNamespace(status_code=code)
        out.webhooks.append(kwargs["json"])
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(alerter, "SERVER_HUB_URL", "http://hub:8080")
    monkeypatch.setattr(alerter, "INTERNAL_API_KEY", "secret")
    monkeypatch.setattr(alerter, "_send_email", fake_email)
    monkeypatch.setattr(alerter, "classify_url", lambda url: UrlVerdict.ALLOWED)
    monkeypatch.setattr(alerter.httpx, "post", fake_post)
    return out


def seed(db, count, kind=SILENT, *, severity="critical", named=True):
    """count agent heartbeats chk-01.. on servers srv-01.., claimed as kind, with
    the record of a bell that showed nothing (SILENT) or the alarm an hour ago
    (BACK). A server is named web-NN through a template assignment unless named
    is False. Returns the entries for send_bundle."""
    silent = kind == SILENT
    if named:
        db.add(MonitorTemplate(id="tpl", name="Linux", check_definitions="[]"))
    entries = []
    for i in range(1, count + 1):
        server_id = f"srv-{i:02d}"
        check = MonitorCheck(
            id=f"chk-{i:02d}",
            server_id=server_id,
            name="Agent Heartbeat",
            check_type="agent_ping",
            config="{}",
            enabled=True,
            severity=severity,
        )
        status = "critical" if silent else "ok"
        state = MonitorState(
            check_id=check.id,
            status=status,
            notified_status=status,
            message=_DOWN if silent else _UP,
            hub_status=None if silent else "critical",
            hub_sent_at=None if silent else _SHOWN,
        )
        db.add_all([check, state])
        if named:
            db.add(
                MonitorTemplateAssignment(
                    id=f"asg-{i:02d}",
                    template_id="tpl",
                    server_id=server_id,
                    server_hostname=f"web-{i:02d}.example.org",
                    server_name=f"web-{i:02d}",
                )
            )
        entries.append((check, state, "ok" if silent else "critical"))
    db.commit()
    return entries


def set_severities(db, entries, severities):
    for (check, _state, _old), severity in zip(entries, severities, strict=True):
        check.severity = severity
    db.commit()


def add_rule(db, rule_id="mail", channel="email", **kw):
    config = (
        {"recipients": ["ops@example.org"]}
        if channel == "email"
        else {"url": "https://hooks.example.org/alert"}
    )
    db.add(
        MonitorAlertRule(
            id=rule_id,
            name=rule_id,
            channel=channel,
            channel_config=json.dumps(config),
            cooldown_minutes=30,
            enabled=True,
            **kw,
        )
    )
    db.commit()


def add_sent_log(db, check_id, minutes_ago):
    db.add(
        MonitorAlertLog(
            alert_rule_id="mail",
            check_id=check_id,
            old_status="ok",
            new_status="critical",
            sent_at=_NOW - timedelta(minutes=minutes_ago),
            success=True,
        )
    )
    db.commit()


def log_rows(db):
    """The alert-log rows send_bundle wrote, as flushed."""
    db.expire_all()
    rows = (
        db.query(MonitorAlertLog)
        .filter(MonitorAlertLog.sent_at == _NOW)
        .order_by(MonitorAlertLog.alert_rule_id, MonitorAlertLog.check_id)
        .all()
    )
    return [
        (r.alert_rule_id, r.check_id, r.old_status, r.new_status, r.success, r.error) for r in rows
    ]


def bell_records(db):
    """(hub_status, hub_sent_at) per member, as flushed: expire_all drops what was
    only set on the objects."""
    db.expire_all()
    rows = db.query(MonitorState).order_by(MonitorState.check_id).all()
    return [(r.hub_status, r.hub_sent_at) for r in rows]


def member_lines(text):
    return [line for line in text.splitlines() if line.startswith("- ")]


def test_bundle_starts_at_three():
    assert BUNDLE_MIN == 3


class TestRules:
    def test_three_members_get_one_mail_and_a_log_row_each(self, db, channels):
        entries = seed(db, 3)
        # Never reported before: reads as ok, as in process_alert.
        entries[0] = (entries[0][0], entries[0][1], None)
        add_rule(db)

        send_bundle(db, SILENT, entries, _NOW)

        assert len(channels.mails) == 1
        check_id, msg = channels.mails[0]
        assert check_id == "chk-01"
        assert msg["subject"] == "[AdminHelper Monitor] CRITICAL: 3 agents not reporting"
        assert msg["text"].splitlines() == [
            "CRITICAL",
            "3 agents not reporting:",
            f"- web-01: {_DOWN}",
            f"- web-02: {_DOWN}",
            f"- web-03: {_DOWN}",
        ]
        assert log_rows(db) == [
            ("mail", f"chk-0{i}", "ok", "critical", True, None) for i in (1, 2, 3)
        ]

    def test_a_rule_for_one_server_sends_its_single_message(self, db, channels):
        entries = seed(db, 3)
        add_rule(db, match_server_id="srv-02")

        send_bundle(db, SILENT, entries, _NOW)

        assert [(cid, msg["subject"]) for cid, msg in channels.mails] == [("chk-02", _SINGLE_DOWN)]
        assert "members" not in channels.mails[0][1]
        assert log_rows(db) == [("mail", "chk-02", "ok", "critical", True, None)]

    def test_members_in_the_rule_cooldown_drop_out_when_silent(self, db, channels):
        entries = seed(db, 3)
        add_rule(db)
        add_sent_log(db, "chk-01", minutes_ago=10)

        send_bundle(db, SILENT, entries, _NOW)

        # Two remain, below the threshold: two single messages.
        assert [(cid, msg["subject"]) for cid, msg in channels.mails] == [
            ("chk-02", _SINGLE_DOWN),
            ("chk-03", _SINGLE_DOWN),
        ]
        assert [row[1] for row in log_rows(db)] == ["chk-02", "chk-03"]

    def test_the_return_passes_the_rule_cooldown(self, db, channels):
        entries = seed(db, 3, BACK)
        add_rule(db)
        add_sent_log(db, "chk-01", minutes_ago=10)

        send_bundle(db, BACK, entries, _NOW)

        assert len(channels.mails) == 1
        msg = channels.mails[0][1]
        assert msg["subject"] == "[AdminHelper Monitor] RECOVERY: 3 agents reporting again"
        assert msg["text"].splitlines() == [
            "RECOVERY",
            "3 agents reporting again:",
            f"- web-01: {_UP}",
            f"- web-02: {_UP}",
            f"- web-03: {_UP}",
        ]
        assert log_rows(db) == [
            ("mail", f"chk-0{i}", "critical", "ok", True, None) for i in (1, 2, 3)
        ]

    @pytest.mark.parametrize(
        ("severities", "label"),
        [
            (("warning", "warning", "warning"), "WARNING"),
            (("warning", "critical", "info"), "CRITICAL"),
            (("info", "warning", "info"), "WARNING"),
            (("info", "info", "info"), "INFO"),
        ],
    )
    def test_label_is_capped_at_the_highest_member_severity(self, db, channels, severities, label):
        entries = seed(db, 3)
        set_severities(db, entries, severities)
        add_rule(db)

        send_bundle(db, SILENT, entries, _NOW)

        msg = channels.mails[0][1]
        assert msg["subject"] == f"[AdminHelper Monitor] {label}: 3 agents not reporting"
        # The text keeps the real status.
        assert msg["text"].splitlines()[0] == "CRITICAL"

    def test_text_lists_fifty_members_and_counts_the_rest(self, db, channels):
        entries = seed(db, 60)
        add_rule(db)

        send_bundle(db, SILENT, entries, _NOW)

        lines = channels.mails[0][1]["text"].splitlines()
        assert lines[1] == "60 agents not reporting:"
        assert member_lines("\n".join(lines)) == [f"- web-{i:02d}: {_DOWN}" for i in range(1, 51)]
        assert lines[-1] == "\u2026 and 10 more"
        assert len(log_rows(db)) == 60

    def test_a_server_without_assignment_is_named_by_its_id(self, db, channels):
        entries = seed(db, 3)
        db.query(MonitorTemplateAssignment).filter_by(server_id="srv-02").delete()
        db.commit()
        add_rule(db)

        send_bundle(db, SILENT, entries, _NOW)

        assert member_lines(channels.mails[0][1]["text"]) == [
            f"- web-01: {_DOWN}",
            f"- srv-02: {_DOWN}",
            f"- web-03: {_DOWN}",
        ]

    def test_webhook_payload_lists_the_members(self, db, channels):
        entries = seed(db, 3)
        db.query(MonitorTemplateAssignment).filter_by(server_id="srv-03").delete()
        db.commit()
        add_rule(db, "hook", channel="webhook")

        send_bundle(db, SILENT, entries, _NOW)

        assert len(channels.webhooks) == 1
        body = channels.webhooks[0]
        assert body["alert_rule"] == "hook"
        assert body["subject"] == "[AdminHelper Monitor] CRITICAL: 3 agents not reporting"
        assert body["server_id"] is None
        assert (body["old_status"], body["new_status"]) == ("ok", "critical")
        assert body["members"] == [
            {
                "check_id": f"chk-0{i}",
                "check_name": "Agent Heartbeat",
                "server_id": f"srv-0{i}",
                "server_name": name,
                "old_status": "ok",
                "new_status": "critical",
                "message": _DOWN,
            }
            for i, name in ((1, "web-01"), (2, "web-02"), (3, None))
        ]

    def test_a_failing_rule_logs_its_members_as_failed(self, db, channels, monkeypatch):
        def boom(config, rule, check, msg):
            raise ValueError("smtp_port abc")

        monkeypatch.setattr(alerter, "_send_email", boom)
        entries = seed(db, 3)
        add_rule(db, "hook", channel="webhook")
        add_rule(db, "mail")

        send_bundle(db, SILENT, entries, _NOW)

        # The other rule still sends.
        assert len(channels.webhooks) == 1
        assert log_rows(db) == [
            ("hook", f"chk-0{i}", "ok", "critical", True, None) for i in (1, 2, 3)
        ] + [
            ("mail", f"chk-0{i}", "ok", "critical", False, "Dispatch failed (ValueError)")
            for i in (1, 2, 3)
        ]


class TestBell:
    def test_three_members_one_event_with_their_servers(self, db, channels):
        entries = seed(db, 3)

        send_bundle(db, SILENT, entries, _NOW)

        assert len(channels.events) == 1
        event = channels.events[0]
        assert event["source_ids"] == ["srv-01", "srv-02", "srv-03"]
        assert "source_id" not in event
        assert (event["severity"], event["new_status"]) == ("critical", "critical")
        assert (event["event_type"], event["category"]) == (
            "monitoring.check.transition",
            "monitoring",
        )
        assert bell_records(db) == [("critical", _NOW)] * 3

    def test_members_in_the_bell_cooldown_drop_out(self, db, channels):
        entries = seed(db, 3)
        recent = _NOW - timedelta(minutes=10)
        state = entries[0][1]
        state.hub_status, state.hub_sent_at = "ok", recent
        db.commit()

        send_bundle(db, SILENT, entries, _NOW)

        # Two remain, below the threshold: two single events.
        assert [(e.get("source_id"), "source_ids" in e) for e in channels.events] == [
            ("srv-02", False),
            ("srv-03", False),
        ]
        assert [e["title"] for e in channels.events] == [_SINGLE_DOWN] * 2
        assert bell_records(db) == [("ok", recent), ("critical", _NOW), ("critical", _NOW)]

    @pytest.mark.parametrize(
        ("kind", "title", "body"),
        [
            (
                SILENT,
                "[AdminHelper Monitor] Agents not reporting",
                "The agents of these servers stopped reporting:",
            ),
            (
                BACK,
                "[AdminHelper Monitor] Agents reporting again",
                "The agents of these servers are reporting again:",
            ),
        ],
    )
    def test_event_text_names_no_server_and_no_count(self, db, channels, kind, title, body):
        # The hub adds the count and the server lines per user, of the servers that
        # user may see; the mail subject with its count is not reused here.
        entries = seed(db, 3, kind)

        send_bundle(db, kind, entries, _NOW)

        assert len(channels.events) == 1
        event = channels.events[0]
        assert (event["title"], event["body"]) == (title, body)
        text = f"{event['title']}\n{event['body']}"
        for check, _state, _old in entries:
            assert check.server_id not in text
        for name in ("web-01", "web-02", "web-03"):
            assert name not in text
        assert not any(ch.isdigit() for ch in text)

    def test_event_carries_the_capped_severity(self, db, channels):
        entries = seed(db, 3, severity="warning")

        send_bundle(db, SILENT, entries, _NOW)

        assert [(e["severity"], e["new_status"]) for e in channels.events] == [
            ("warning", "critical")
        ]
        assert bell_records(db) == [("warning", _NOW)] * 3

    def test_one_event_per_level(self, db, channels):
        # Kevin 2026-10-20: alert.triggered reaches only servers whose own check is
        # critical, and min_severity applies per server.
        entries = seed(db, 6)
        set_severities(db, entries, ("warning", "critical") * 3)

        send_bundle(db, SILENT, entries, _NOW)

        assert sorted((e["severity"], e["source_ids"]) for e in channels.events) == [
            ("critical", ["srv-02", "srv-04", "srv-06"]),
            ("warning", ["srv-01", "srv-03", "srv-05"]),
        ]
        assert bell_records(db) == [("warning", _NOW), ("critical", _NOW)] * 3

    def test_a_level_below_the_threshold_goes_out_on_its_own(self, db, channels):
        # Three members, but no level has three: three single events.
        entries = seed(db, 3)
        set_severities(db, entries, ("warning", "critical", "warning"))

        send_bundle(db, SILENT, entries, _NOW)

        assert all("source_ids" not in e for e in channels.events)
        assert sorted((e["source_id"], e["severity"]) for e in channels.events) == [
            ("srv-01", "warning"),
            ("srv-02", "critical"),
            ("srv-03", "warning"),
        ]
        assert bell_records(db) == [("warning", _NOW), ("critical", _NOW), ("warning", _NOW)]

    def test_info_heartbeats_never_reach_the_bell(self, db, channels):
        entries = seed(db, 3, severity="info")

        send_bundle(db, SILENT, entries, _NOW)

        assert channels.events == []
        assert bell_records(db) == [(None, None)] * 3

    def test_return_is_grouped_by_the_level_its_alarms_reached_the_bell_with(self, db, channels):
        # All severities are warning now; the even ones alarmed the bell as
        # critical before the severity was lowered.
        entries = seed(db, 6, BACK, severity="warning")
        for i, (_check, state, _old) in enumerate(entries, start=1):
            state.hub_status = "critical" if i % 2 == 0 else "warning"
        db.commit()

        send_bundle(db, BACK, entries, _NOW)

        assert sorted(
            (e["severity"], e["new_status"], e["source_ids"]) for e in channels.events
        ) == [
            ("critical", "ok", ["srv-02", "srv-04", "srv-06"]),
            ("warning", "ok", ["srv-01", "srv-03", "srv-05"]),
        ]
        # A recovery leaves hub_sent_at as it was.
        assert bell_records(db) == [("ok", _SHOWN)] * 6

    def test_a_single_return_reaches_the_bell_at_the_level_of_its_alarm(self, db, channels):
        # Below the threshold, as process_alert: the alarm reached the bell as
        # critical, the severity was lowered to warning afterwards.
        entries = seed(db, 2, BACK, severity="warning")

        send_bundle(db, BACK, entries, _NOW)

        assert [
            (e["source_id"], e["severity"], e["new_status"], e["title"]) for e in channels.events
        ] == [
            (f"srv-0{i}", "critical", "ok", "[AdminHelper Monitor] RECOVERY: Agent Heartbeat")
            for i in (1, 2)
        ]
        assert bell_records(db) == [("ok", _SHOWN)] * 2

    def test_a_rejected_event_records_nothing(self, db, channels):
        channels.hub_code = 403
        entries = seed(db, 3)

        send_bundle(db, SILENT, entries, _NOW)

        assert len(channels.events) == 1
        assert bell_records(db) == [(None, None)] * 3

    def test_a_rejected_single_event_records_nothing_for_its_member(self, db, channels):
        channels.hub_codes = [403, 202]
        entries = seed(db, 2)

        send_bundle(db, SILENT, entries, _NOW)

        assert [e["source_id"] for e in channels.events] == ["srv-01", "srv-02"]
        assert bell_records(db) == [(None, None), ("critical", _NOW)]

    def test_no_database_access_between_the_posts(self, db, channels):
        # Review T11: no write of this session may hold a row across hub I/O, as in
        # process_alert (5.3). Two warning single events and one critical bundle;
        # the rule runs first and leaves its alert-log rows to be flushed.
        entries = seed(db, 5)
        set_severities(db, entries, ("warning", "warning", "critical", "critical", "critical"))
        add_rule(db)
        engine = db.get_bind()

        def on_sql(conn, cursor, statement, parameters, context, executemany):
            channels.timeline.append("sql")

        event.listen(engine, "before_cursor_execute", on_sql)
        try:
            send_bundle(db, SILENT, entries, _NOW)
        finally:
            event.remove(engine, "before_cursor_execute", on_sql)

        posts = [i for i, step in enumerate(channels.timeline) if step == "post"]
        assert len(posts) == 3
        assert "sql" not in channels.timeline[posts[0] : posts[-1]]
        assert "sql" in channels.timeline[posts[-1] :]  # the records, flushed after
        assert bell_records(db) == [("warning", _NOW)] * 2 + [("critical", _NOW)] * 3

    def test_more_servers_than_the_hub_takes_go_in_several_events(self, db, channels):
        entries = seed(db, HUB_MAX_IDS + 1, named=False)

        send_bundle(db, SILENT, entries, _NOW)

        assert [len(e["source_ids"]) for e in channels.events] == [HUB_MAX_IDS, 1]
        assert channels.events[1]["source_ids"] == [f"srv-{HUB_MAX_IDS + 1:02d}"]
        assert bell_records(db) == [("critical", _NOW)] * (HUB_MAX_IDS + 1)

    def test_a_heartbeat_without_server_goes_on_its_own(self, db, channels):
        entries = seed(db, 4)
        entries[3][0].server_id = None
        db.commit()

        send_bundle(db, SILENT, entries, _NOW)

        assert [e.get("source_ids") for e in channels.events] == [
            None,
            ["srv-01", "srv-02", "srv-03"],
        ]
        assert channels.events[0]["source_id"] is None
        assert channels.events[0]["title"] == _SINGLE_DOWN
        assert bell_records(db) == [("critical", _NOW)] * 4

    def test_below_the_threshold_without_server_all_go_on_their_own(self, db, channels):
        entries = seed(db, 3)
        entries[2][0].server_id = None
        db.commit()

        send_bundle(db, SILENT, entries, _NOW)

        assert [e.get("source_id") for e in channels.events] == ["srv-01", "srv-02", None]
        assert all("source_ids" not in e for e in channels.events)


# flush_agent_alerts (T12). The job runs every 30 s; the tests run it at the
# minutes after _NOW they pass to at().
_BUNDLE_SUBJECT = {
    SILENT: "[AdminHelper Monitor] CRITICAL: {n} agents not reporting",
    BACK: "[AdminHelper Monitor] RECOVERY: {n} agents reporting again",
}
_SINGLE_SUBJECT = {SILENT: _SINGLE_DOWN, BACK: "[AdminHelper Monitor] RECOVERY: Agent Heartbeat"}
# notified_status of a heartbeat before and after it is reported.
_OPEN = {SILENT: "ok", BACK: "critical"}
_REPORTED = {SILENT: "critical", BACK: "ok"}


def at(minutes):
    return _NOW + timedelta(minutes=minutes)


@pytest.fixture()
def run_job(db, channels, monkeypatch):
    """flush_agent_alerts against the test database, with sessions of its own as
    in production, at a fixed clock the test sets per run: process_alert on the
    single path reads the same clock."""
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=db.get_bind()))
    clock = SimpleNamespace(now=_NOW)
    monkeypatch.setattr(alerter, "utcnow_naive", lambda: clock.now)

    def run(now):
        clock.now = now
        flush_agent_alerts(now)

    return run


def open_heartbeat(db, i, since, kind=SILENT):
    """Agent heartbeat chk-NN on server srv-NN that went silent (BACK: came back)
    at since and is not reported yet: the discrepancy the job collects. A BACK
    heartbeat's alarm reached the bell an hour before it came back."""
    silent = kind == SILENT
    check_id = f"chk-{i:02d}"
    db.add(
        MonitorCheck(
            id=check_id,
            server_id=f"srv-{i:02d}",
            name="Agent Heartbeat",
            check_type="agent_ping",
            config="{}",
            enabled=True,
            severity="critical",
        )
    )
    db.add(
        MonitorState(
            check_id=check_id,
            status="critical" if silent else "ok",
            notified_status=_OPEN[kind],
            since=since,
            message=_DOWN if silent else _UP,
            hub_status=None if silent else "critical",
            hub_sent_at=None if silent else since - timedelta(hours=1),
        )
    )
    db.commit()


def notified(db):
    """notified_status per check, as committed."""
    db.expire_all()
    return {s.check_id: s.notified_status for s in db.query(MonitorState).all()}


def logged(db):
    """(check_id, new_status) of every alert-log row, as committed."""
    db.expire_all()
    rows = db.query(MonitorAlertLog).order_by(MonitorAlertLog.check_id).all()
    return [(r.check_id, r.new_status) for r in rows]


def mails(channels):
    return [(check_id, msg["subject"]) for check_id, msg in channels.mails]


def bell(channels):
    """Per hub event the servers it names: a bundle's list, a single's id."""
    return [e["source_ids"] if "source_ids" in e else e["source_id"] for e in channels.events]


def before_the_claim(monkeypatch, db, change):
    """Between the job's selection and its claim, another session applies
    change(session, now) and commits, as an evaluation of the scheduler or an
    API request would. Only in the first run."""
    select = alert_bundle._candidates
    raced = []

    def racing(session, now):
        found = select(session, now)
        if not raced:
            raced.append(now)
            other = sessionmaker(bind=db.get_bind())()
            change(other, now)
            other.commit()
            other.close()
        return found

    monkeypatch.setattr(alert_bundle, "_candidates", racing)


def back_to_ok(check_id):
    """The heartbeat check_id comes back to ok."""

    def change(session, now):
        session.query(MonitorState).filter_by(check_id=check_id).update(
            {"status": "ok", "since": now}
        )

    return change


def maintenance_starts(server_id):
    """A maintenance window of server_id starts."""

    def change(session, now):
        session.add(
            MonitorMaintenance(
                id="mw",
                server_id=server_id,
                kind="once",
                starts_at=now,
                ends_at=now + timedelta(hours=1),
            )
        )

    return change


def test_window_is_five_minutes():
    assert BUNDLE_WINDOW == timedelta(minutes=5)


class TestFlush:
    @pytest.mark.parametrize("kind", [SILENT, BACK])
    @pytest.mark.parametrize("third", [2, 4])
    def test_three_within_five_minutes_one_bundle_once_the_third_is_there(
        self, db, channels, run_job, kind, third
    ):
        add_rule(db)
        open_heartbeat(db, 1, at(0), kind)
        open_heartbeat(db, 2, at(1), kind)
        for step in range(2, 2 * third):
            run_job(at(step / 2))
        assert (channels.mails, channels.events) == ([], [])
        assert notified(db) == dict.fromkeys(("chk-01", "chk-02"), _OPEN[kind])

        open_heartbeat(db, 3, at(third), kind)
        run_job(at(third))

        assert mails(channels) == [("chk-01", _BUNDLE_SUBJECT[kind].format(n=3))]
        assert member_lines(channels.mails[0][1]["text"]) == [
            f"- srv-0{i}: {_DOWN if kind == SILENT else _UP}" for i in (1, 2, 3)
        ]
        assert bell(channels) == [["srv-01", "srv-02", "srv-03"]]
        assert notified(db) == dict.fromkeys(("chk-01", "chk-02", "chk-03"), _REPORTED[kind])
        # The run commits what send_bundle wrote: an alert-log row per member.
        assert logged(db) == [(f"chk-0{i}", _REPORTED[kind]) for i in (1, 2, 3)]

    @pytest.mark.parametrize("kind", [SILENT, BACK])
    def test_two_wait_five_minutes_then_go_out_on_their_own(self, db, channels, run_job, kind):
        add_rule(db)
        open_heartbeat(db, 1, at(0), kind)
        open_heartbeat(db, 2, at(1), kind)

        run_job(at(5) - timedelta(seconds=1))
        assert (channels.mails, channels.events) == ([], [])

        run_job(at(5))
        assert mails(channels) == [("chk-01", _SINGLE_SUBJECT[kind])]
        assert bell(channels) == ["srv-01"]
        assert notified(db) == {"chk-01": _REPORTED[kind], "chk-02": _OPEN[kind]}

        run_job(at(6))
        assert mails(channels) == [
            ("chk-01", _SINGLE_SUBJECT[kind]),
            ("chk-02", _SINGLE_SUBJECT[kind]),
        ]
        assert bell(channels) == ["srv-01", "srv-02"]
        assert notified(db) == dict.fromkeys(("chk-01", "chk-02"), _REPORTED[kind])

    @pytest.mark.parametrize("mute", ["maintenance window", "host ping"])
    def test_a_muted_heartbeat_does_not_count_and_stays_open(self, db, channels, run_job, mute):
        add_rule(db)
        for i in (1, 2, 3):
            open_heartbeat(db, i, at(0))
        if mute == "maintenance window":
            db.add(
                MonitorMaintenance(
                    id="mw", server_id="srv-03", kind="once", starts_at=at(-60), ends_at=at(60)
                )
            )
        else:
            db.add_all(
                [
                    MonitorCheck(
                        id="ping-03",
                        server_id="srv-03",
                        name="Host Ping",
                        check_type="ping",
                        config="{}",
                        enabled=True,
                        template_def_id=alerter.HOST_PING_DEF_ID,
                    ),
                    MonitorState(check_id="ping-03", status="critical", notified_status="critical"),
                ]
            )
        db.commit()

        # Two count: below the threshold and young, they wait.
        run_job(at(0))
        assert (channels.mails, channels.events) == ([], [])

        run_job(at(5))
        assert mails(channels) == [("chk-01", _SINGLE_DOWN), ("chk-02", _SINGLE_DOWN)]
        assert bell(channels) == ["srv-01", "srv-02"]
        assert notified(db)["chk-03"] == "ok"

    def test_only_enabled_heartbeats_count(self, db, channels, run_job):
        add_rule(db)
        for i in (1, 2, 3):
            open_heartbeat(db, i, at(0))
        db.query(MonitorCheck).filter_by(id="chk-03").update({"enabled": False})
        # An open alarm of another check type is not the job's. On a server
        # without a heartbeat nothing mutes it: only its type keeps it out of a
        # bundle with chk-01 and chk-02.
        db.add_all(
            [
                MonitorCheck(
                    id="res-01",
                    server_id="srv-09",
                    name="Resources",
                    check_type="agent_resources",
                    config="{}",
                    enabled=True,
                ),
                MonitorState(
                    check_id="res-01", status="critical", notified_status="ok", since=at(-60)
                ),
            ]
        )
        db.commit()

        run_job(at(0))
        assert (channels.mails, channels.events) == ([], [])

        run_job(at(5))
        assert mails(channels) == [("chk-01", _SINGLE_DOWN), ("chk-02", _SINGLE_DOWN)]
        assert (notified(db)["chk-03"], notified(db)["res-01"]) == ("ok", "ok")

    def test_old_discrepancies_after_a_maintenance_window_go_out_bundled_at_once(
        self, db, channels, run_job
    ):
        add_rule(db)
        for i in (1, 2, 3, 4):
            open_heartbeat(db, i, at(-60))
        db.add(MonitorMaintenance(id="mw", kind="once", starts_at=at(-90), ends_at=at(10)))
        db.commit()

        run_job(at(9.5))
        assert (channels.mails, channels.events) == ([], [])

        run_job(at(10))
        assert mails(channels) == [("chk-01", _BUNDLE_SUBJECT[SILENT].format(n=4))]
        assert bell(channels) == [["srv-01", "srv-02", "srv-03", "srv-04"]]
        assert set(notified(db).values()) == {"critical"}
        # The bell's record of each member is committed with the run.
        assert bell_records(db) == [("critical", at(10))] * 4

    def test_a_heartbeat_back_before_the_claim_drops_out(self, db, channels, run_job, monkeypatch):
        add_rule(db)
        for i in (1, 2, 3, 4):
            open_heartbeat(db, i, at(0))
        before_the_claim(monkeypatch, db, back_to_ok("chk-04"))

        run_job(at(0))

        assert mails(channels) == [("chk-01", _BUNDLE_SUBJECT[SILENT].format(n=3))]
        assert bell(channels) == [["srv-01", "srv-02", "srv-03"]]
        assert notified(db) == {
            "chk-01": "critical",
            "chk-02": "critical",
            "chk-03": "critical",
            "chk-04": "ok",
        }

    @pytest.mark.parametrize("kind", [SILENT, BACK])
    def test_a_heartbeat_muted_before_the_claim_drops_out_and_stays_open(
        self, db, channels, run_job, monkeypatch, kind
    ):
        # The claim decides on the muting again, as process_alert does under its
        # lock: a maintenance window that starts after the selection counts.
        add_rule(db)
        for i in (1, 2, 3, 4):
            open_heartbeat(db, i, at(0), kind)
        before_the_claim(monkeypatch, db, maintenance_starts("srv-04"))

        run_job(at(0))

        assert mails(channels) == [("chk-01", _BUNDLE_SUBJECT[kind].format(n=3))]
        assert bell(channels) == [["srv-01", "srv-02", "srv-03"]]
        assert notified(db) == {
            "chk-01": _REPORTED[kind],
            "chk-02": _REPORTED[kind],
            "chk-03": _REPORTED[kind],
            "chk-04": _OPEN[kind],
        }

    def test_fewer_than_three_left_at_the_claim_wait_for_the_window(
        self, db, channels, run_job, monkeypatch
    ):
        # Two left are two like any other: no bundle, no claim, the window.
        add_rule(db)
        for i in (1, 2, 3):
            open_heartbeat(db, i, at(0))
        before_the_claim(monkeypatch, db, back_to_ok("chk-03"))

        run_job(at(0))
        assert (channels.mails, channels.events) == ([], [])
        assert notified(db) == dict.fromkeys(("chk-01", "chk-02", "chk-03"), "ok")

        run_job(at(5))
        assert mails(channels) == [("chk-01", _SINGLE_DOWN), ("chk-02", _SINGLE_DOWN)]

    def test_bundle_and_singles_in_one_run_reach_the_bell_once_each(self, db, channels, run_job):
        # Three gone silent are bundled, two old returns go out on their own, in
        # the same run; a second run right after sends nothing: the sent-state is
        # the buffer, also for a run in a new session.
        add_rule(db)
        for i in (1, 2, 3):
            open_heartbeat(db, i, at(0))
        for i in (4, 5):
            open_heartbeat(db, i, at(-10), BACK)

        run_job(at(0))
        run_job(at(0.5))

        assert mails(channels) == [
            ("chk-01", _BUNDLE_SUBJECT[SILENT].format(n=3)),
            ("chk-04", _SINGLE_SUBJECT[BACK]),
            ("chk-05", _SINGLE_SUBJECT[BACK]),
        ]
        assert bell(channels) == [["srv-01", "srv-02", "srv-03"], "srv-04", "srv-05"]
        assert [(e["severity"], e["new_status"]) for e in channels.events] == [
            ("critical", "critical"),
            ("critical", "ok"),
            ("critical", "ok"),
        ]
        shown = at(-10) - timedelta(hours=1)
        assert bell_records(db) == [("critical", at(0))] * 3 + [("ok", shown)] * 2
        assert notified(db) == {
            "chk-01": "critical",
            "chk-02": "critical",
            "chk-03": "critical",
            "chk-04": "ok",
            "chk-05": "ok",
        }

    def test_a_failing_run_is_logged_and_its_claim_stands(
        self, db, channels, run_job, monkeypatch, caplog
    ):
        def boom(*args):
            raise RuntimeError("bundle broke")

        monkeypatch.setattr(alert_bundle, "send_bundle", boom)
        add_rule(db)
        for i in (1, 2, 3):
            open_heartbeat(db, i, at(0))

        run_job(at(0))

        assert [r.getMessage() for r in caplog.records if r.name == "monitor.alert_bundle"] == [
            "Agent alert bundle failed"
        ]
        # Claimed before any I/O, as process_alert: at most once, never twice.
        assert notified(db) == dict.fromkeys(("chk-01", "chk-02", "chk-03"), "critical")
        monkeypatch.setattr(alert_bundle, "send_bundle", send_bundle)
        run_job(at(0.5))
        assert (channels.mails, channels.events) == ([], [])
