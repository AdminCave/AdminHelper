# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Producer/whitelist consistency for hook events (audit 2.42).

Every event a router fires must be in hooks.schemas.VALID_EVENTS, otherwise a
hook can never subscribe to it — create_hook/update_hook reject unknown events
with 422, so the emission is dead. The playbook.* events had drifted out of the
whitelist; this guard keeps producers and the whitelist in sync.
"""

import re
from pathlib import Path

from app.modules.hooks.schemas import VALID_EVENTS

_APP_DIR = Path(__file__).resolve().parent.parent / "app"
# \s* spans newlines (Python regex), so multi-line calls count; queue_event's literal
# follows its session argument.
_FIRE_EVENT = re.compile(r'fire_event\(\s*"([^"]+)"')
_QUEUE_EVENT = re.compile(r'queue_event\(\s*\w+,\s*"([^"]+)"')
_FIRE_EVENT_CALL = re.compile(r"\bfire_event\(")
# Sources without a transaction of their own; everything else queues on its session, so
# a rolled-back change fires nothing (R-0689). app/main.py leaves with server.startup.
_FIRE_EVENT_ALLOWED = {
    "core/events.py",
    "main.py",
    "modules/notifications/router.py",
    "scheduler_main.py",
}


def _fired_event_literals() -> set[str]:
    fired: set[str] = set()
    for py in _APP_DIR.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        fired.update(_FIRE_EVENT.findall(text))
        fired.update(_QUEUE_EVENT.findall(text))
    return fired


def test_only_sources_without_a_transaction_call_fire_event():
    callers = {
        py.relative_to(_APP_DIR).as_posix()
        for py in _APP_DIR.rglob("*.py")
        if _FIRE_EVENT_CALL.search(py.read_text(encoding="utf-8"))
    }
    assert "modules/notifications/router.py" in callers  # the scan is not silently empty
    assert callers - _FIRE_EVENT_ALLOWED == set()


def test_every_fired_event_is_subscribable():
    fired = _fired_event_literals()
    # Sanity: the scan actually found the known producers (not silently empty).
    assert {"connection.created", "alert.triggered"} <= fired
    missing = sorted(fired - set(VALID_EVENTS))
    assert missing == [], f"event literals absent from VALID_EVENTS: {missing}"


def test_web_hook_picker_matches_valid_events():
    """The web hook editor carries its own copy of the event list
    (apps/web/src/lib/utils/hooks.ts HOOK_EVENTS) plus one i18n label per
    event. That copy has drifted twice (playbook.*, alert.triggered) — an
    event missing there is invisible in the UI and can only be subscribed via
    the raw API. Pin both lists to exact equality and require the labels."""
    web_root = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib"
    hooks_ts = (web_root / "utils" / "hooks.ts").read_text(encoding="utf-8")
    m = re.search(r"HOOK_EVENTS = \[(.*?)\] as const", hooks_ts, re.S)
    assert m, "HOOK_EVENTS array not found in apps/web/src/lib/utils/hooks.ts"
    web_events = set(re.findall(r"'([^']+)'", m.group(1)))
    assert web_events == set(VALID_EVENTS), (
        f"web HOOK_EVENTS drifted from VALID_EVENTS — "
        f"missing in web: {sorted(set(VALID_EVENTS) - web_events)}, "
        f"unknown to server: {sorted(web_events - set(VALID_EVENTS))}"
    )

    dictionaries = (web_root / "i18n" / "dictionaries.ts").read_text(encoding="utf-8")
    unlabeled = sorted(ev for ev in VALID_EVENTS if dictionaries.count(f"'hook.event.{ev}'") < 2)
    assert unlabeled == [], f"events without DE+EN hook.event labels: {unlabeled}"
