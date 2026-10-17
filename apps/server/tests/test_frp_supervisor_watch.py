# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scheduler job turns the events of the frps supervisor into bell notifications.

applied reaches the admins and the users with tunnel access (assigned to a server with at least
one enabled tunnel), nobody else; rejected, crashed, copy_changed and start_refused reach the
admins as a warning, stopped as info, started nobody; every other event the reader knows
reaches someone.
Each event is told once (source_type "frps", source_id "<boot>:<seq>"), a missing or unreadable
status file tells nothing, and the texts carry no value from the file. A file that shows new
boots or sequence numbers on every read gets at most LIMIT notifications per hour, and an event
older than an hour is no news."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.auth import hash_password
from app.modules.frp import supervisor_watch
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.supervisor_status import EVENTS, REASONS
from app.modules.frp.supervisor_watch import LIMIT, WINDOW, notify_supervisor_events
from app.modules.hooks import scheduler as sched
from app.modules.notifications.models import Notification
from app.modules.servers.models import Server
from app.modules.users.models import User

BOOT = "0123456789abcdef"
APPLIED_BODY = (
    "Der FRP-Server hat die neue Konfiguration übernommen und neu gestartet; "
    "Tunnel waren kurz getrennt."
)
AGENT_HINT = "Agent-Tunnel verbinden sich innerhalb von bis zu ~5 Minuten neu."


def _now() -> datetime:
    # The rows get created_at from the database clock, so the job runs on the real one.
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(seq, event, at, *, reason="none", token_changed=False) -> dict:
    return {
        "seq": seq,
        "event": event,
        "at": _iso(at),
        "reason": reason,
        "tokenChanged": token_changed,
    }


@pytest.fixture()
def status_file(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    monkeypatch.setattr(supervisor_watch, "STATUS_FILE", path)
    return path


def _write(path, events, now, *, boot=BOOT, applied_hash="a" * 64, rejected_hash=None):
    path.write_text(
        json.dumps(
            {
                "v": 1,
                "boot": boot,
                "heartbeat": _iso(now),
                "state": "running",
                "reason": "none",
                "since": _iso(now - timedelta(minutes=10)),
                "appliedHash": applied_hash,
                "rejectedHash": rejected_hash,
                "events": events,
            }
        )
    )


def _user(db, username, *, is_admin=False, servers=()):
    user = User(username=username, hashed_password=hash_password("passpass123"), is_admin=is_admin)
    user.servers = list(servers)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def people(db_session):
    """An admin, a user on a server with an enabled tunnel, one on servers with a disabled
    tunnel and with none, and one without any server."""
    db = db_session
    db.add(
        FrpServerConfig(
            id="cfg-1",
            name="Default",
            server_addr="frps.example.net",
            bind_port=7000,
            auth_token="token-with-enough-length",
        )
    )
    servers = {sid: Server(id=sid, name=sid, hostname=f"{sid}.example.test") for sid in "abc"}
    db.add_all(servers.values())
    db.commit()
    for tid, sid, enabled, port in (("t-a", "a", True, 6000), ("t-b", "b", False, 6001)):
        db.add(
            FrpTunnel(
                id=tid,
                server_id=sid,
                frp_config_id="cfg-1",
                name=f"{sid}-ssh",
                tunnel_type="stcp",
                protocol="ssh",
                local_port=22,
                secret_key="stcp-secret",
                visitor_port=port,
                enabled=enabled,
            )
        )
    db.commit()
    return SimpleNamespace(
        admin=_user(db, "boss", is_admin=True),
        tunnel_member=_user(db, "tunnel-member", servers=[servers["a"]]),
        idle_member=_user(db, "idle-member", servers=[servers["b"], servers["c"]]),
        loner=_user(db, "loner"),
    )


def _rows(db, user=None) -> list[Notification]:
    query = db.query(Notification).filter(Notification.source_type == "frps")
    if user is not None:
        query = query.filter(Notification.user_id == user.id)
    return query.order_by(Notification.id).all()


def test_applied_reaches_the_admins_and_the_users_with_tunnel_access(
    db_session, people, status_file
):
    now = _now()
    _write(status_file, [_event(1, "started", now), _event(2, "applied", now)], now)

    assert notify_supervisor_events(db_session, now=now) == 2

    rows = _rows(db_session)
    assert sorted(row.user_id for row in rows) == sorted([people.admin.id, people.tunnel_member.id])
    # A user whose servers have no enabled tunnel, and one without a server, get no row.
    assert _rows(db_session, people.idle_member) == []
    assert _rows(db_session, people.loner) == []
    for row in rows:
        assert (row.severity, row.category, row.event_type) == (
            "info",
            "lifecycle",
            "lifecycle.frp.server.applied",
        )
        assert (row.source_type, row.source_id) == ("frps", f"{BOOT}:2")
        assert row.title == "FRP-Server neu gestartet"
        assert row.body == APPLIED_BODY


def test_a_new_token_adds_that_agent_tunnels_take_up_to_five_minutes(
    db_session, people, status_file
):
    now = _now()
    _write(status_file, [_event(3, "applied", now, token_changed=True)], now)

    notify_supervisor_events(db_session, now=now)

    rows = _rows(db_session)
    assert len(rows) == 2
    assert all(row.body == f"{APPLIED_BODY} {AGENT_HINT}" for row in rows)


@pytest.mark.parametrize(
    ("event", "reason", "severity", "title", "body"),
    [
        (
            "rejected",
            "cert_expired",
            "warning",
            "Neue FRP-Konfiguration nicht übernommen",
            "Grund: Zertifikat abgelaufen. "
            "Der FRP-Server läuft mit der letzten gültigen Konfiguration weiter.",
        ),
        (
            "rejected",
            "input_unreadable",
            "warning",
            "Neue FRP-Konfiguration nicht übernommen",
            "Grund: Konfigurations- oder Zertifikatsdatei nicht lesbar oder zu groß. "
            "Der FRP-Server läuft mit der letzten gültigen Konfiguration weiter.",
        ),
        (
            "rejected",
            "input_unstable",
            "warning",
            "Neue FRP-Konfiguration nicht übernommen",
            "Grund: Konfiguration ändert sich laufend. "
            "Die Konfiguration wird erst übernommen, sobald sie sich nicht mehr ändert.",
        ),
        (
            "crashed",
            "none",
            "warning",
            "FRP-Server startet wiederholt neu",
            "Der FRP-Server bricht wiederholt ab und wird automatisch neu gestartet.",
        ),
        (
            "stopped",
            "config_missing",
            "info",
            "FRP-Server gestoppt",
            "Es gibt keine FRP-Konfiguration mehr.",
        ),
        (
            "copy_changed",
            "none",
            "warning",
            "Geprüfte Kopie der FRP-Konfiguration verändert",
            "Die geprüfte Kopie, aus der der FRP-Server startet, hat sich nach ihrer Übernahme "
            "verändert. Sie wurde verworfen; der FRP-Server startet nur aus einer neu geprüften "
            "Kopie der Konfiguration.",
        ),
        (
            "start_refused",
            "processes_left",
            "warning",
            "FRP-Server nicht gestartet",
            "Grund: Prozesse des FRP-Servers ließen sich nicht beenden. Der FRP-Server bleibt "
            "gestoppt, bis sich die Konfiguration ändert oder der frps-Container neu startet.",
        ),
    ],
)
def test_every_event_but_applied_and_started_reaches_the_admins_only(
    db_session, people, status_file, event, reason, severity, title, body
):
    now = _now()
    _write(status_file, [_event(5, event, now, reason=reason)], now)

    assert notify_supervisor_events(db_session, now=now) == 1

    (row,) = _rows(db_session)
    assert row.user_id == people.admin.id
    assert (row.severity, row.event_type, row.title, row.body) == (
        severity,
        f"lifecycle.frp.server.{event}",
        title,
        body,
    )
    assert (row.source_type, row.source_id) == ("frps", f"{BOOT}:5")


RUNS_ON = "Der FRP-Server läuft mit der letzten gültigen Konfiguration weiter."
UNTIL_STABLE = "Die Konfiguration wird erst übernommen, sobald sie sich nicht mehr ändert."


@pytest.mark.parametrize("reason", sorted(REASONS))
def test_only_an_unstable_input_does_not_claim_that_frps_runs_on(
    db_session, people, status_file, reason
):
    # The supervisor reports an unstable input also when no frps runs (no valid copy).
    now = _now()
    _write(status_file, [_event(6, "rejected", now, reason=reason)], now)

    notify_supervisor_events(db_session, now=now)

    (row,) = _rows(db_session)
    if reason == "input_unstable":
        assert UNTIL_STABLE in row.body and RUNS_ON not in row.body
    else:
        assert RUNS_ON in row.body and UNTIL_STABLE not in row.body


@pytest.mark.parametrize("event", sorted(EVENTS - {"started"}))
def test_every_event_the_reader_knows_but_started_tells_someone(
    db_session, people, status_file, event
):
    now = _now()
    _write(status_file, [_event(7, event, now)], now)
    assert notify_supervisor_events(db_session, now=now) >= 1


def test_started_tells_nobody(db_session, people, status_file):
    now = _now()
    _write(status_file, [_event(1, "started", now)], now)
    assert notify_supervisor_events(db_session, now=now) == 0
    assert _rows(db_session) == []


def test_a_second_run_writes_nothing_twice(db_session, people, status_file):
    now = _now()
    events = [
        _event(1, "started", now),
        _event(2, "applied", now),
        _event(3, "rejected", now, reason="verify_failed"),
    ]
    _write(status_file, events, now)

    assert notify_supervisor_events(db_session, now=now) == 3
    assert notify_supervisor_events(db_session, now=now) == 0
    assert len(_rows(db_session)) == 3

    # A new event in the ring is told on its own.
    _write(status_file, [*events, _event(4, "stopped", now, reason="config_missing")], now)
    assert notify_supervisor_events(db_session, now=now) == 1
    assert [row.source_id for row in _rows(db_session)][-1] == f"{BOOT}:4"


@pytest.mark.parametrize(
    "content",
    [None, b"", b"{not json", json.dumps({"v": 1, "boot": BOOT}).encode()],
    ids=["missing", "empty", "not-json", "incomplete"],
)
def test_a_missing_or_unreadable_status_file_tells_nothing(
    db_session, people, status_file, content
):
    if content is not None:
        status_file.write_bytes(content)
    assert notify_supervisor_events(db_session, now=_now()) == 0
    assert _rows(db_session) == []


def test_the_texts_carry_no_value_from_the_file(db_session, people, status_file, monkeypatch):
    monkeypatch.setattr(supervisor_watch, "LIMIT", 100)
    now = _now()
    boot = "fedcba9876543210"
    times = [now - timedelta(minutes=7, seconds=13 + i) for i in range(len(REASONS) + 3)]
    hashes = {"applied_hash": "c" * 64, "rejected_hash": "d" * 64}
    _write(
        status_file,
        [
            _event(40001, "applied", times[0], reason="none", token_changed=True),
            _event(40002, "stopped", times[1], reason="config_missing"),
            _event(40003, "crashed", times[2], reason="verify_failed"),
        ],
        now,
        boot=boot,
        **hashes,
    )
    notify_supervisor_events(db_session, now=now)
    # Every reason code once, each in a file of its own (a ring holds at most 8 events).
    for i, reason in enumerate(sorted(REASONS)):
        _write(
            status_file,
            [_event(50001 + i, "rejected", times[3 + i], reason=reason)],
            now,
            boot=f"{boot[:-2]}{i:02x}",
            **hashes,
        )
        notify_supervisor_events(db_session, now=now)

    rows = _rows(db_session)
    rejected = {row.body for row in rows if row.event_type.endswith(".rejected")}
    assert len(rejected) == len(REASONS)  # a text of its own for every reason
    values = [boot, boot[:-2], "c" * 64, "d" * 64, "40001", "40002", "40003", "5000"]
    values += [_iso(when) for when in [*times, now]]
    values += [_iso(when)[11:19] for when in [*times, now]]
    for row in rows:
        for value in values:
            assert value not in row.title
            assert value not in row.body


def test_a_flood_of_new_boots_and_sequence_numbers_stays_within_the_limit(
    db_session, people, status_file
):
    now = _now()
    kinds = ("applied", "rejected", "stopped", "crashed")
    for run in range(30):
        _write(
            status_file,
            [
                _event(run * 8 + i, kinds[i % 4], now, reason="cert_missing", token_changed=True)
                for i in range(8)
            ],
            now,
            boot=f"{run:016x}",
        )
        notify_supervisor_events(db_session, now=now)

    assert len({row.source_id for row in _rows(db_session)}) == LIMIT
    assert len(_rows(db_session, people.admin)) == LIMIT
    assert len(_rows(db_session, people.tunnel_member)) <= LIMIT


def test_over_the_limit_the_newest_events_are_told(db_session, people, status_file, monkeypatch):
    monkeypatch.setattr(supervisor_watch, "LIMIT", 2)
    now = _now()
    _write(
        status_file,
        [
            _event(1, "applied", now),
            _event(2, "rejected", now, reason="cert_missing"),
            _event(3, "stopped", now, reason="config_missing"),
            _event(4, "crashed", now),
        ],
        now,
    )

    notify_supervisor_events(db_session, now=now)

    assert {row.source_id for row in _rows(db_session)} == {f"{BOOT}:3", f"{BOOT}:4"}


def test_the_limit_holds_for_an_hour_and_then_frees_again(db_session, people, status_file):
    now = _now()
    for run in range(2):
        _write(
            status_file,
            [_event(i, "crashed", now) for i in range(LIMIT // 2 + 1)],
            now,
            boot=f"{run:016x}",
        )
        notify_supervisor_events(db_session, now=now)
    assert len(_rows(db_session)) == LIMIT

    _write(status_file, [_event(1, "crashed", now)], now, boot="ffffffffffffffff")
    assert notify_supervisor_events(db_session, now=now) == 0

    later = now + WINDOW + timedelta(minutes=1)
    _write(status_file, [_event(1, "crashed", later)], later, boot="ffffffffffffffff")
    assert notify_supervisor_events(db_session, now=later) == 1


def test_an_event_older_than_an_hour_is_no_news(db_session, people, status_file):
    now = _now()
    _write(
        status_file,
        [
            _event(1, "crashed", now - WINDOW - timedelta(minutes=1)),
            _event(2, "rejected", now - WINDOW + timedelta(minutes=1), reason="cert_paths"),
        ],
        now,
    )

    assert notify_supervisor_events(db_session, now=now) == 1
    assert [row.source_id for row in _rows(db_session)] == [f"{BOOT}:2"]


def test_the_watch_runs_every_15_seconds_as_a_system_job():
    sched.schedule_frps_supervisor_watch()
    try:
        job = sched.scheduler.get_job(sched._FRPS_SUPERVISOR_WATCH_JOB_ID)
        assert job is not None
        assert job.trigger.interval == timedelta(seconds=15)
    finally:
        if sched.scheduler.get_job(sched._FRPS_SUPERVISOR_WATCH_JOB_ID):
            sched.scheduler.remove_job(sched._FRPS_SUPERVISOR_WATCH_JOB_ID)


def test_the_job_hands_its_own_session_to_the_watch_and_closes_it(monkeypatch):
    import app.core.database as database

    closed, seen = [], []

    class _Session:
        def close(self):
            closed.append(True)

    session = _Session()
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    monkeypatch.setattr(supervisor_watch, "notify_supervisor_events", lambda db: seen.append(db))

    sched._run_frps_supervisor_watch()

    assert seen == [session]
    assert closed == [True]
