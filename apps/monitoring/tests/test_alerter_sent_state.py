# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sent-state semantics (docs/features/alert-sent-state.md).

T2: the pure decision matrix — notify on a real discrepancy, silently record an
ok that never had a reported problem, and never treat unknown as reported.
T6 adds the end-to-end scenarios (F1/F2/F7) on top."""

import pytest

from app.alerter import resolve_notification

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
