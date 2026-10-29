# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sent-state semantics (docs/features/alert-sent-state.md).

T2: the pure decision matrix — notify on a real discrepancy, silently record an
ok that never had a reported problem, and never treat unknown as reported.
T6 adds the end-to-end scenarios (F1/F2/F7) on top."""

import json
from datetime import timedelta

import pytest

from app.alerter import resolve_notification
from app.core.time import utcnow_naive
from app.models import (
    MonitorAlertRule,
    MonitorCheck,
    MonitorMaintenance,
    MonitorState,
)

# --- T2: full decision matrix ------------------------------------------------

# (notified_status, new_status) -> expected decision. notified None/"pending"
# mean "never reported"; "unknown" as notified can only occur via legacy
# backfill (a state that was unknown at deploy time) and counts as unreported.
_MATRIX = [
    # new_status == "ok"
    (None, "ok", "silent_ack"),
    ("pending", "ok", "silent_ack"),
    ("unknown", "ok", "silent_ack"),
    ("ok", "ok", "skip"),
    ("warning", "ok", "notify"),  # real recovery
    ("critical", "ok", "notify"),  # real recovery
    # new_status == "warning"
    (None, "warning", "notify"),
    ("pending", "warning", "notify"),
    ("unknown", "warning", "notify"),
    ("ok", "warning", "notify"),
    ("warning", "warning", "skip"),
    ("critical", "warning", "notify"),  # improvement is still a report
    # new_status == "critical"
    (None, "critical", "notify"),
    ("pending", "critical", "notify"),
    ("unknown", "critical", "notify"),
    ("ok", "critical", "notify"),
    ("warning", "critical", "notify"),  # escalation
    ("critical", "critical", "skip"),
    # new_status == "unknown" — never notifies, never acknowledges
    (None, "unknown", "skip"),
    ("pending", "unknown", "skip"),
    ("unknown", "unknown", "skip"),
    ("ok", "unknown", "skip"),
    ("warning", "unknown", "skip"),
    ("critical", "unknown", "skip"),
]


@pytest.mark.parametrize(("notified", "new", "expected"), _MATRIX)
def test_matrix(notified, new, expected):
    assert resolve_notification(notified, new) == expected


def test_unknown_preserves_pending_discrepancy():
    # The core of F1/F2: a suppressed problem (notified=ok, status=critical)
    # must keep notifying-eligibility across an unknown phase.
    assert resolve_notification("ok", "unknown") == "skip"
    assert resolve_notification("ok", "critical") == "notify"


# --- T6: end-to-end scenarios F1/F2/F7 through the real push pipeline --------


@pytest.fixture()
def scenario(client_db, monkeypatch, request):
    """Shared client_db (conftest) + spied _dispatch: drives the agent push
    pipeline end to end (BackgroundTasks run after each response).

    consecutive_oks is 1 — one ok push recovers, as before the hold (R-0424) —
    unless a test passes another value indirectly (_OKS_1_AND_2, _OKS_2)."""
    from app import alerter

    client, factory = client_db
    consecutive_oks = getattr(request, "param", 1)

    dispatched: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        alerter,
        "_dispatch",
        lambda rule, check, msg: (
            dispatched.append((check.id, msg["old_status"], msg["new_status"])) or (True, None)
        ),
    )

    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-1",
                server_id="srv-1",
                name="Resources",
                check_type="agent_resources",
                config=json.dumps({"cpu_warn": 80, "cpu_crit": 95}),
                enabled=True,
                consecutive_fails=1,
                consecutive_oks=consecutive_oks,
            )
        )
        # cooldown 0: successive reports in this test are milliseconds apart —
        # the production default (30) would damp them like a real repeat.
        db.add(
            MonitorAlertRule(
                id="r1",
                name="rule",
                channel="webhook",
                channel_config=json.dumps({"url": "https://hooks.example/x"}),
                cooldown_minutes=0,
            )
        )
        db.commit()

    yield client, factory, dispatched


# The F1/F2 scenarios also run with the recovery hold (consecutive_oks 2): it must
# neither swallow a reported recovery nor report a problem that was never reported
# (Kevin 2026-10-20: only a reported problem is held).
_OKS_1_AND_2 = pytest.mark.parametrize("scenario", [1, 2], indirect=True, ids=["oks1", "oks2"])
_OKS_2 = pytest.mark.parametrize("scenario", [2], indirect=True, ids=["oks2"])


def _push(client, cpu=None):
    body = {} if cpu is None else {"resources": {"cpu_percent": cpu}}
    assert client.post("/agent/srv-1/report", json=body).status_code == 200


def _set_host_down(factory, down: bool):
    with factory() as db:
        if not db.query(MonitorCheck).filter_by(id="hb-1").first():
            db.add(
                MonitorCheck(
                    id="hb-1",
                    server_id="srv-1",
                    name="Heartbeat",
                    check_type="agent_ping",
                    config="{}",
                    enabled=True,
                )
            )
            db.add(MonitorState(check_id="hb-1", status="critical", notified_status="critical"))
            db.commit()
        db.query(MonitorState).filter_by(check_id="hb-1").update(
            {"status": "critical" if down else "ok"}
        )
        db.commit()


def test_f1_problem_during_host_down_is_caught_up_after_recovery(scenario):
    client, factory, dispatched = scenario
    _set_host_down(factory, True)

    # Problem arises WHILE the host is down: suppressed, nothing reported.
    _push(client, cpu=99)
    assert dispatched == []

    # Host recovers; the check itself stays critical (no transition) — the
    # next push must catch the report up.
    _set_host_down(factory, False)
    _push(client, cpu=99)
    assert dispatched == [("chk-1", "ok", "critical")]

    # The later recovery now refers to a REPORTED alert.
    _push(client, cpu=5)
    assert dispatched == [("chk-1", "ok", "critical"), ("chk-1", "critical", "ok")]


@_OKS_2
def test_f1_caught_up_problem_recovers_after_the_hold(scenario):
    client, factory, dispatched = scenario
    _set_host_down(factory, True)
    _push(client, cpu=99)  # suppressed
    _set_host_down(factory, False)
    _push(client, cpu=99)  # caught up: now a reported problem
    assert dispatched == [("chk-1", "ok", "critical")]

    _push(client, cpu=5)  # held
    assert len(dispatched) == 1
    _push(client, cpu=5)
    assert dispatched == [("chk-1", "ok", "critical"), ("chk-1", "critical", "ok")]


@_OKS_2
def test_hold_after_host_down_never_reports_a_muted_problem(scenario):
    # security T2 probe B: the problem was muted while the host was down and is
    # gone by the first push after it. Nothing was reported, so nothing is held —
    # a held critical would have been caught up as a fresh alert.
    client, factory, dispatched = scenario
    _set_host_down(factory, True)
    _push(client, cpu=99)
    _set_host_down(factory, False)
    _push(client, cpu=5)
    _push(client, cpu=5)
    assert dispatched == []


def _set_host_ping(factory, status):
    """The server's Host Ping (template "Host Ping") at status, as reported."""
    with factory() as db:
        if not db.query(MonitorCheck).filter_by(id="hp-1").first():
            db.add(
                MonitorCheck(
                    id="hp-1",
                    server_id="srv-1",
                    name="Host Ping",
                    check_type="ping",
                    config="{}",
                    enabled=True,
                    template_def_id="host-ping",
                )
            )
            db.add(MonitorState(check_id="hp-1", status=status, notified_status=status))
        db.query(MonitorState).filter_by(check_id="hp-1").update(
            {"status": status, "notified_status": status}
        )
        db.commit()


def _heartbeat(factory, status):
    """One evaluation of the server's heartbeat at status: the state is written,
    then the alerter gets it through dispatch_alert_bg, the dispatcher of every
    path. Its first evaluation finds nothing reported yet."""
    from app.check_engine import dispatch_alert_bg

    with factory() as db:
        if not db.query(MonitorCheck).filter_by(id="hb-1").first():
            db.add(
                MonitorCheck(
                    id="hb-1",
                    server_id="srv-1",
                    name="Heartbeat",
                    check_type="agent_ping",
                    config="{}",
                    enabled=True,
                )
            )
            db.add(MonitorState(check_id="hb-1", status="ok", notified_status="ok"))
            db.flush()
        row = db.query(MonitorState).filter_by(check_id="hb-1").one()
        old, row.status = row.status, status
        db.commit()
    dispatch_alert_bg("hb-1", old, status)


def test_heartbeat_muted_by_the_host_ping_is_caught_up_once_the_ping_is_back(scenario):
    # R-0424: a critical Host Ping mutes the heartbeat (the heartbeat never mutes
    # the Host Ping). Is the ping back while the agent stays silent, the next
    # evaluation of the heartbeat reports its outage, once.
    _client, factory, dispatched = scenario
    _set_host_ping(factory, "critical")
    _heartbeat(factory, "critical")
    assert dispatched == []

    _set_host_ping(factory, "ok")
    _heartbeat(factory, "critical")  # no transition: the catch-up
    assert dispatched == [("hb-1", "ok", "critical")]
    _heartbeat(factory, "critical")
    assert dispatched == [("hb-1", "ok", "critical")]


@_OKS_1_AND_2
def test_f1_problem_resolved_during_host_down_never_reports(scenario):
    client, factory, dispatched = scenario
    _set_host_down(factory, True)

    _push(client, cpu=99)  # suppressed
    _push(client, cpu=5)  # resolves while still down -> silent_ack
    _set_host_down(factory, False)
    _push(client, cpu=5)  # nothing pending
    assert dispatched == []  # no phantom alert, no phantom recovery


def _window(factory, active: bool):
    now = utcnow_naive()
    with factory() as db:
        if not db.query(MonitorMaintenance).filter_by(id="m1").first():
            db.add(
                MonitorMaintenance(
                    id="m1",
                    server_id="srv-1",
                    kind="once",
                    starts_at=now - timedelta(hours=1),
                    ends_at=now + timedelta(hours=1),
                    enabled=True,
                )
            )
        db.query(MonitorMaintenance).filter_by(id="m1").update({"enabled": active})
        db.commit()


@_OKS_1_AND_2
def test_f2_recovery_inside_window_is_reported_after_it_ends(scenario):
    client, factory, dispatched = scenario

    # Alert BEFORE the window: reported normally.
    _push(client, cpu=99)
    assert dispatched == [("chk-1", "ok", "critical")]

    # Recovery INSIDE the window: muted, sent-state keeps the discrepancy.
    _window(factory, True)
    _push(client, cpu=5)
    assert len(dispatched) == 1

    # Window over: the recovery for the previously reported alert catches up.
    _window(factory, False)
    _push(client, cpu=5)
    assert dispatched[-1] == ("chk-1", "critical", "ok")
    assert len(dispatched) == 2


@_OKS_1_AND_2
def test_f2_transition_fully_inside_window_stays_silent(scenario):
    client, factory, dispatched = scenario
    _window(factory, True)
    _push(client, cpu=99)  # critical inside the window: muted
    _push(client, cpu=5)  # back to ok inside the window: silent_ack territory
    _window(factory, False)
    _push(client, cpu=5)  # no discrepancy left
    assert dispatched == []


@_OKS_1_AND_2
def test_f2_problem_outlasting_window_is_caught_up(scenario):
    client, factory, dispatched = scenario
    _window(factory, True)
    _push(client, cpu=99)  # critical inside the window: muted
    assert dispatched == []
    _window(factory, False)
    _push(client, cpu=99)  # still critical after the window -> catch-up
    assert dispatched == [("chk-1", "ok", "critical")]


@_OKS_2
def test_hold_after_window_never_reports_a_muted_problem(scenario):
    # security T2 probe A: critical only inside the window, ok from the first push
    # after it — never reported, so not held and never caught up.
    client, factory, dispatched = scenario
    _window(factory, True)
    _push(client, cpu=99)
    _window(factory, False)
    _push(client, cpu=5)
    _push(client, cpu=5)
    assert dispatched == []


@_OKS_2
def test_hold_keeps_the_reported_warning_not_a_muted_critical(scenario):
    # Kevin 2026-10-20: reported warning, critical only inside the window. The hold
    # stays at the reported warning — no "warning -> critical" for a problem that
    # is going away — and the recovery comes from warning.
    client, factory, dispatched = scenario
    _push(client, cpu=92)
    assert dispatched == [("chk-1", "ok", "warning")]
    _window(factory, True)
    _push(client, cpu=99)  # critical, muted
    _window(factory, False)
    _push(client, cpu=5)  # held at warning
    assert len(dispatched) == 1
    _push(client, cpu=5)
    assert dispatched == [("chk-1", "ok", "warning"), ("chk-1", "warning", "ok")]


def test_f7_unknown_flapping_produces_zero_notifications(scenario):
    client, factory, dispatched = scenario
    _push(client, cpu=5)
    for _ in range(3):
        _push(client)  # no resources block -> unknown
        _push(client, cpu=5)
    assert dispatched == []


def test_f7_recovery_after_reported_problem_survives_unknown_phase(scenario):
    client, factory, dispatched = scenario
    _push(client, cpu=99)  # reported alert
    _push(client)  # unknown: silent
    _push(client, cpu=5)  # ok: exactly one recovery
    assert dispatched == [("chk-1", "ok", "critical"), ("chk-1", "critical", "ok")]
