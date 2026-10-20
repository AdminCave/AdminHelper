# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checker/desktop consistency for the systemd unit type suffixes.

The services line of the desktop dashboard colours a failed unit like the
checker rates it: a failed .service (or a name without a unit suffix, a Windows
service) red, any other failed unit yellow. For that it carries its own copy of
ServiceProcessChecker._UNIT_TYPES in SecServices.svelte. A comment asking to keep
it in sync is not a gate: if a suffix is added on one side only, the desktop
shows such a unit red while the check stays warning (or the other way round),
and nothing turns red. Same remedy as test_push_only_ui_sync.py.
"""

import re
from pathlib import Path

from app.checkers.agent import ServiceProcessChecker

_UI_SECTION = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "desktop"
    / "ui"
    / "src"
    / "components"
    / "monitoring"
    / "section"
    / "SecServices.svelte"
)
_LIST = re.compile(r"const UNIT_TYPES = \[(.*?)\]", re.S)


def test_ui_unit_types_match_checker():
    src = _UI_SECTION.read_text(encoding="utf-8")
    m = _LIST.search(src)
    assert m, f"UNIT_TYPES not found in {_UI_SECTION}"
    ui_types = set(re.findall(r"'(\.[a-z]+)'", m.group(1)))
    # Sanity: the scan actually parsed entries instead of silently matching empty.
    assert ".service" in ui_types
    backend = set(ServiceProcessChecker._UNIT_TYPES)
    assert ui_types == backend, (
        f"UI copy drifted: only in UI {sorted(ui_types - backend)}, "
        f"only in checker {sorted(backend - ui_types)}"
    )
