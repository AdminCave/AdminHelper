# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What goes when a server is deleted.

The server lives in the server's database, so no row here has a foreign key to it
and nothing cascades: checks, alert rules, assignments, tombstones, the agent key,
maintenance windows, liveness, host facts and dismissed suggestions are deleted by
hand. The scheduler follows after the commit, like every template sync.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import (
    MonitorAgentKey,
    MonitorAgentLiveness,
    MonitorAlertRule,
    MonitorCheck,
    MonitorCheckTombstone,
    MonitorHostFacts,
    MonitorMaintenance,
    MonitorTemplateAssignment,
    MonitorTemplateSuggestionDismissal,
)
from app.template_sync import SchedulerAction, apply_scheduler_actions

logger = logging.getLogger("monitor.server_cleanup")


def cleanup_server(db: Session, server_id: str) -> dict:
    """Deletes all monitoring data of a server (on server deletion)."""
    actions: list[SchedulerAction] = []
    # Delete checks (incl. states via CASCADE)
    checks = db.query(MonitorCheck).filter(MonitorCheck.server_id == server_id).all()
    for check in checks:
        actions.append(("remove", check.id, None, None))
        db.delete(check)

    # Delete alerts with match_server_id
    alerts = db.query(MonitorAlertRule).filter(MonitorAlertRule.match_server_id == server_id).all()
    for alert in alerts:
        db.delete(alert)

    # Delete assignments, and their tombstones: those have no foreign key to the
    # server, which lives in the server's database
    db.query(MonitorTemplateAssignment).filter(
        MonitorTemplateAssignment.server_id == server_id,
    ).delete()
    db.query(MonitorCheckTombstone).filter(MonitorCheckTombstone.server_id == server_id).delete()

    # Delete agent key
    db.query(MonitorAgentKey).filter(MonitorAgentKey.server_id == server_id).delete()

    # Server-scoped maintenance windows would otherwise become orphans no UI
    # can reach (the only maintenance view is the per-server tab), and a stale
    # liveness row would be re-hydrated on every restart (T42). Global windows
    # (server_id NULL) stay.
    db.query(MonitorMaintenance).filter(MonitorMaintenance.server_id == server_id).delete()
    db.query(MonitorAgentLiveness).filter(MonitorAgentLiveness.server_id == server_id).delete()

    # Host facts and ignored template suggestions: no foreign key to the server either
    db.query(MonitorHostFacts).filter(MonitorHostFacts.server_id == server_id).delete()
    db.query(MonitorTemplateSuggestionDismissal).filter(
        MonitorTemplateSuggestionDismissal.server_id == server_id,
    ).delete()

    db.commit()
    apply_scheduler_actions(actions)
    logger.info(
        "Server %s cleanup: %d checks, %d alerts deleted", server_id, len(checks), len(alerts)
    )
    return {"checksDeleted": len(checks), "alertsDeleted": len(alerts)}
