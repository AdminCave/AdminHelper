# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared alerter-test helpers (6.132). Extracted from test_alerter so test_alerter_hub can reuse them
without importing another test module — a rename or cleanup of test_alerter would otherwise break the
hub suite with an ImportError.

seed_bell_check, bell_record and overlap_first_hub_post drive two dispatches of one check through
real sessions; test_alerter_hub runs them on SQLite, test_check_engine_concurrency on Postgres.

assert_every_reader_reads is the one check of a checker's _details that the checker tests share.

no_env_proxy keeps a proxy from the developer's shell off the webhook tests that mean the direct,
pinned connection."""

import json
import math
from types import SimpleNamespace


def make_rule(**kw):
    """Minimal MonitorAlertRule stub with the fields read by the logic."""
    defaults = dict(
        id="rule-1",
        name="r",
        match_severity=None,
        match_server_id=None,
        channel="webhook",
        channel_config="{}",
        cooldown_minutes=30,
        enabled=True,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def make_check(**kw):
    """Minimal MonitorCheck stub."""
    defaults = dict(
        id="check-1",
        name="c",
        check_type="ping",
        server_id="srv-1",
        severity="critical",
        template_def_id=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def make_msg(**kw):
    """Fake build_message() result — built once per transition in process_alert
    now (2.30) and passed to _dispatch / _send_* / emit_to_hub."""
    defaults = dict(
        check_name="c",
        check_type="ping",
        server_id="srv-1",
        severity="critical",
        old_status="ok",
        new_status="critical",
        is_recovery=False,
        icon="",
        subject="S",
        text="T",
    )
    defaults.update(kw)
    return defaults


class _ListQuery:
    """query(Model)-shim returning a fixed list (filter chainable)."""

    def __init__(self, items):
        self._items = items

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._items


class _FirstQuery:
    """query(Model)-shim returning a fixed single row (filter chainable)."""

    def __init__(self, row):
        self._row = row

    def filter(self, *args, **kwargs):
        return self

    def with_for_update(self, *args, **kwargs):
        return self

    def first(self):
        return self._row

    def update(self, values, synchronize_session=None):
        # The alerter's bulk UPDATE (handing back a bell slot after a failed hub
        # POST). A stub cannot evaluate the WHERE, so the values go onto the row
        # as they are; the condition itself is pinned against real databases
        # (test_alerter_hub, test_check_engine_concurrency).
        if self._row is None:
            return 0
        for key, value in values.items():
            setattr(self._row, key, value)
        return 1


class _CapturingDb:
    """Fake DB for process_alert: provides the rules list, collects add()
    and flush()/commit() calls. process_alert commits the sent-state claim
    itself (claim-then-dispatch) and flushes the alert-log rows for the
    caller's commit. Maintenance-window queries are
    answered model-aware (default: none active)."""

    def __init__(self, rules, maintenance=None, state=None):
        self._rules = rules
        self._maintenance = maintenance or []
        # The sent-state load queries the MonitorState ENTITY; None = no row
        # (process_alert then falls back to the caller's old_status). NOTE:
        # _host_is_down queries the MonitorState.status COLUMN and gets None
        # from first() here (nothing stands critical); a subclass answers it
        # otherwise (test_alerter's _HostDownDb).
        self._state = state
        self.added = []
        self.flushed = False
        self.committed = False

    def query(self, *args, **kwargs):
        from app.models import MonitorMaintenance, MonitorState

        if args and args[0] is MonitorMaintenance:
            return _ListQuery(self._maintenance)
        if args and args[0] is MonitorState:
            return _FirstQuery(self._state)
        return self

    def join(self, *args, **kwargs):
        # _host_is_down joins state<->check; chainable like filter().
        return self

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rules

    def first(self):
        # build_message queries MonitorState here; no state row in these tests.
        return None

    def add(self, entry):
        self.added.append(entry)

    def flush(self):
        self.flushed = True

    def commit(self):
        # process_alert commits the sent-state claim itself (claim-then-
        # dispatch); the fake only records that it happened.
        self.committed = True


def seed_bell_check(factory, *, status, notified_status, hub_status=None, hub_sent_at=None):
    """One enabled critical ping check with its state row, committed; returns its id."""
    from app.models import MonitorCheck, MonitorState

    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-bell",
                server_id="srv-1",
                name="bell",
                check_type="ping",
                config="{}",
                enabled=True,
                severity="critical",
            )
        )
        db.add(
            MonitorState(
                check_id="chk-bell",
                status=status,
                notified_status=notified_status,
                hub_status=hub_status,
                hub_sent_at=hub_sent_at,
            )
        )
        db.commit()
    return "chk-bell"


def bell_record(factory, check_id):
    """(hub_status, hub_sent_at) as committed."""
    from app.models import MonitorState

    with factory() as db:
        row = db.query(MonitorState).filter_by(check_id=check_id).one()
        return row.hub_status, row.hub_sent_at


def overlap_first_hub_post(monkeypatch, factory, check_id, second_status, first_code=202):
    """Arm a hub whose FIRST POST runs a second dispatch of the check to its end
    before it answers with first_code: the check moves to second_status and
    dispatch_alert_bg runs again — the second dispatch of one check while the
    first is still in its hub POST (R-0424 T6 review). A tuple of statuses moves
    the check to each in turn, with one dispatch per move. Every later POST
    answers 202. Returns the list that gets the new_status of every POST."""
    from app import alerter
    from app.check_engine import dispatch_alert_bg
    from app.models import MonitorState

    monkeypatch.setattr(alerter, "SERVER_HUB_URL", "http://hub:8080")
    monkeypatch.setattr(alerter, "INTERNAL_API_KEY", "secret")
    posted = []
    statuses = (second_status,) if isinstance(second_status, str) else second_status

    def fake_post(url, **kwargs):
        posted.append(kwargs["json"]["new_status"])
        if len(posted) > 1:
            return SimpleNamespace(status_code=202)
        for status in statuses:
            with factory() as db:
                row = db.query(MonitorState).filter_by(check_id=check_id).one()
                old_status, row.status = row.status, status
                db.commit()
            dispatch_alert_bg(check_id, old_status, status)
        return SimpleNamespace(status_code=first_code)

    monkeypatch.setattr(alerter.httpx, "post", fake_post)
    return posted


def assert_every_reader_reads(details):
    """No NaN or Infinity token, and every number converts to a finite float (a strict reader
    such as serde_json rejects a larger integer as out of range). _details goes as it is into the
    answers of GET /status and GET /checks, which the desktop reads as a whole."""
    json.dumps(details, allow_nan=False)
    stack = [details]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                finite = math.isfinite(float(value))
            except OverflowError:
                finite = False
            assert finite, f"number not representable as a finite float: {str(value)[:20]}"


def no_env_proxy(monkeypatch):
    """Clears the proxy variables, upper and lower case. With a proxy for the URL's scheme
    pinned_client hands the request to the proxy, unpinned, so a test of the direct path
    would pass in a shell that sets one without ever reaching the pin."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
