# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Producer/consumer consistency for PUSH_ONLY_TYPES (code-review-fixes T2).

The desktop UI greys out the "run now" button for push-evaluated checks, which
means it carries its own copy of the type list in
apps/desktop/ui/src/lib/models/monitoring.ts. A comment asking to keep it in
sync is not a gate — and the dangerous direction is silent: if a type LEAVES
push_only here, the UI keeps a working action greyed out forever and explains it
with the wrong reason, without anything turning red.

Same failure mode and same remedy as apps/server/tests/test_event_whitelist.py,
where the web hook-event list had drifted twice.
"""

import re
from pathlib import Path

from app.check_types import PUSH_ONLY_TYPES

_UI_MODEL = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "desktop"
    / "ui"
    / "src"
    / "lib"
    / "models"
    / "monitoring.ts"
)
_LIST = re.compile(r"const PUSH_ONLY_CHECK_TYPES = \[(.*?)\]", re.S)


def test_ui_push_only_list_matches_backend():
    src = _UI_MODEL.read_text(encoding="utf-8")
    m = _LIST.search(src)
    assert m, f"PUSH_ONLY_CHECK_TYPES not found in {_UI_MODEL}"
    ui_types = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    # Sanity: the scan actually parsed entries instead of silently matching empty.
    assert "smart_health" in ui_types
    assert ui_types == PUSH_ONLY_TYPES, (
        f"UI copy drifted: only in UI {sorted(ui_types - PUSH_ONLY_TYPES)}, "
        f"only in backend {sorted(PUSH_ONLY_TYPES - ui_types)}"
    )


def test_agent_ping_stays_runnable():
    """agent_ping measures the ABSENCE of a push and is scheduler-evaluated.
    If it ever became push_only, the UI would stop offering a manual run for the
    one check where that is most useful during an incident."""
    assert "agent_ping" not in PUSH_ONLY_TYPES
