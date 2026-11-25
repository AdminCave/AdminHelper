# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What goes when a server is deleted.

The server lives in the server's database, so no row here has a foreign key to it
and nothing cascades: checks, alert rules, assignments, tombstones, the agent key,
maintenance windows, liveness, host facts, dismissed suggestions, the discovery and
its findings, the service inventory and its error lines are deleted by hand. The
scheduler follows after the commit, like every template sync.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.bell_catch_up import AllClear, deleted_all_clear, send_all_clears
from app.models import (
    MonitorAgentKey,
    MonitorAgentLiveness,
    MonitorAlertRule,
    MonitorCheck,
    MonitorCheckTombstone,
    MonitorDiscovery,
    MonitorException,
    MonitorFinding,
    MonitorHostFacts,
    MonitorMaintenance,
    MonitorModuleTombstone,
    MonitorServiceInventory,
    MonitorServiceLog,
    MonitorTemplateAssignment,
    MonitorTemplateSuggestionDismissal,
)
from app.template_sync import SchedulerAction, apply_scheduler_actions

logger = logging.getLogger("monitor.server_cleanup")


def known_server_ids(db: Session) -> set[str]:
    """Every server id that monitoring data of cleanup_server hangs on (global rows with a
    NULL server id do not count)."""
    columns = (
        MonitorCheck.server_id,
        MonitorAlertRule.match_server_id,
        MonitorTemplateAssignment.server_id,
        MonitorCheckTombstone.server_id,
        MonitorModuleTombstone.server_id,
        MonitorAgentKey.server_id,
        MonitorMaintenance.server_id,
        MonitorException.server_id,
        MonitorAgentLiveness.server_id,
        MonitorHostFacts.server_id,
        MonitorTemplateSuggestionDismissal.server_id,
        MonitorDiscovery.server_id,
        MonitorFinding.server_id,
        MonitorServiceInventory.server_id,
        MonitorServiceLog.server_id,
    )
    ids: set[str] = set()
    for column in columns:
        ids.update(sid for (sid,) in db.query(column).filter(column.isnot(None)).distinct())
    return ids


def cleanup_server(
    db: Session,
    server_id: str,
    send_clears: Callable[[list[AllClear]], None] = send_all_clears,
) -> dict:
    """Deletes all monitoring data of a server (on server deletion). send_clears
    gets the all-clears of the deleted checks; the route hands them to a
    background task, so the hub calls do not hold up its answer (R-1622)."""
    actions: list[SchedulerAction] = []
    # Delete checks (incl. states via CASCADE)
    checks = db.query(MonitorCheck).filter(MonitorCheck.server_id == server_id).all()
    clears = [clear for check in checks if (clear := deleted_all_clear(db, check))]
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
    db.query(MonitorModuleTombstone).filter(MonitorModuleTombstone.server_id == server_id).delete()

    # Delete agent key
    db.query(MonitorAgentKey).filter(MonitorAgentKey.server_id == server_id).delete()

    # Server-scoped maintenance windows would otherwise become orphans no UI
    # can reach (the only maintenance view is the per-server tab), and a stale
    # liveness row would be re-hydrated on every restart (T42). Global windows
    # (server_id NULL) stay. The exceptions of the server go with it, ended ones
    # too: their trail names a server that is gone (R-1636). The frozen
    # maintenance rows go as before: known_server_ids still counts them.
    db.query(MonitorMaintenance).filter(MonitorMaintenance.server_id == server_id).delete()
    db.query(MonitorException).filter(MonitorException.server_id == server_id).delete()
    db.query(MonitorAgentLiveness).filter(MonitorAgentLiveness.server_id == server_id).delete()

    # Host facts and ignored template suggestions: no foreign key to the server either
    db.query(MonitorHostFacts).filter(MonitorHostFacts.server_id == server_id).delete()
    db.query(MonitorTemplateSuggestionDismissal).filter(
        MonitorTemplateSuggestionDismissal.server_id == server_id,
    ).delete()

    # The discovery inventory and its findings: no foreign key to the server either
    db.query(MonitorDiscovery).filter(MonitorDiscovery.server_id == server_id).delete()
    db.query(MonitorFinding).filter(MonitorFinding.server_id == server_id).delete()

    # The service inventory and the error lines of its failed services: same reason
    db.query(MonitorServiceInventory).filter(
        MonitorServiceInventory.server_id == server_id
    ).delete()
    db.query(MonitorServiceLog).filter(MonitorServiceLog.server_id == server_id).delete()

    db.commit()
    apply_scheduler_actions(actions)
    send_clears(clears)
    logger.info(
        "Server %s cleanup: %d checks, %d alerts deleted", server_id, len(checks), len(alerts)
    )
    return {"checksDeleted": len(checks), "alertsDeleted": len(alerts)}
