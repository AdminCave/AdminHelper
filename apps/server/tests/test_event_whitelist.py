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
# \s* spans newlines (Python regex), so multi-line fire_event( "..." ) calls count.
_FIRE_EVENT = re.compile(r'fire_event\(\s*"([^"]+)"')


def _fired_event_literals() -> set[str]:
    fired: set[str] = set()
    for py in _APP_DIR.rglob("*.py"):
        fired.update(_FIRE_EVENT.findall(py.read_text(encoding="utf-8")))
    return fired


def test_every_fired_event_is_subscribable():
    fired = _fired_event_literals()
    # Sanity: the scan actually found the known producers (not silently empty).
    assert "connection.created" in fired
    missing = sorted(fired - set(VALID_EVENTS))
    assert missing == [], f"fire_event literals absent from VALID_EVENTS: {missing}"
