# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared alerter-test helpers (6.132). Extracted from test_alerter so test_alerter_hub can reuse them
without importing another test module — a rename or cleanup of test_alerter would otherwise break the
hub suite with an ImportError."""

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
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def make_msg(**kw):
    """Fake _build_message() result — built once per transition in process_alert
    now (2.30) and passed to _dispatch / _send_* / _emit_to_hub."""
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


class _CapturingDb:
    """Fake DB for process_alert: provides the rules list, collects add()
    and flush() calls. process_alert only flushes the alert log now; the
    caller owns the commit (see the H7 fix). Maintenance-window queries are
    answered model-aware (default: none active)."""

    def __init__(self, rules, maintenance=None):
        self._rules = rules
        self._maintenance = maintenance or []
        self.added = []
        self.flushed = False

    def query(self, *args, **kwargs):
        from app.models import MonitorMaintenance

        if args and args[0] is MonitorMaintenance:
            return _ListQuery(self._maintenance)
        return self

    def join(self, *args, **kwargs):
        # _host_is_down joins state<->check; chainable like filter().
        return self

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rules

    def first(self):
        # _build_message queries MonitorState here; no state row in these tests.
        return None

    def add(self, entry):
        self.added.append(entry)

    def flush(self):
        self.flushed = True
