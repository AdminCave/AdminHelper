# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent push endpoint — receives metrics from remote servers."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session

from app.check_engine import apply_result, dispatch_alert_bg, log_transition
from app.check_types import PUSH_ONLY_TYPES
from app.checkers import get_checker
from app.checkers.agent import (
    EXCLUDED_FSTYPES,
    NO_MOUNT,
    agent_number,
    capped_objects,
    entry_text,
    record_agent_report,
)
from app.core.auth import require_agent
from app.core.bounds import find_unstorable
from app.core.database import get_db
from app.core.time import utcnow_naive
from app.core.victoria import format_line, victoria
from app.models import MonitorAgentLiveness, MonitorCheck, MonitorState
from app.template_suggestions import store_host_facts

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/agent/{server_id}/report")
def agent_report(
    server_id: str,
    report: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth_server_id: str = Depends(require_agent),
):
    """Agent pushes metrics directly to the monitoring service."""
    if auth_server_id != "__internal__" and auth_server_id != server_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="API key does not belong to this server"
        )

    record_agent_report(server_id)
    _record_liveness(db, server_id)
    _refuse_unstorable_report(server_id, report)

    _store_host_facts(db, server_id, report)
    lines = _report_lines(server_id, report)
    if lines:
        victoria.write(lines)

    checks_updated = 0
    # (check_id, old_status, new_status) for each sent-state discrepancy; dispatched in
    # the background after the response so webhook/SMTP never block the request.
    pending_alerts: list[tuple[str, str, str]] = []
    transitions: list[tuple[str, str, str, str]] = []
    # Collect all per-check result metrics and flush them in one write after the loop, instead of one
    # victoria POST per check — the usual ~6 checks per report would otherwise be up to 6 extra HTTP
    # roundtrips (each with a 10s timeout) on the report path (5.20).
    check_lines: list[str] = []
    now = utcnow_naive()
    for check in _push_checks(db, server_id):
        # Isolate each check: a single broken check.config (or a checker raising)
        # must not abort the evaluation of all other checks for this server
        # (same isolation as the scheduler path in check_engine.execute_check).
        try:
            result_lines, transition, alert = _evaluate_push_check(
                db, check, server_id, report, now
            )
        except Exception:
            logger.exception("Auswertung von Check '%s' fehlgeschlagen", check.name)
            continue
        check_lines.extend(result_lines)
        if transition is not None:
            transitions.append(transition)
        if alert is not None:
            pending_alerts.append(alert)
        checks_updated += 1

    if checks_updated:
        _commit_evaluation(db, transitions)
    # Flush all collected per-check metrics in a single write (5.20).
    if check_lines:
        victoria.write(check_lines)
    # Only after the state is durably committed: dispatch alerts off-request.
    for check_id, old_s, new_s in pending_alerts:
        background_tasks.add_task(dispatch_alert_bg, check_id, old_s, new_s)

    return {"status": "ok", "metricsWritten": len(lines), "checksUpdated": checks_updated}


def _record_liveness(db: Session, server_id: str) -> None:
    # Persist liveness so agent_ping survives service restarts. Own commit: the
    # shared commit of the evaluation only happens when agent checks exist, and a
    # failed persist must only cost the hydration, never the report.
    try:
        db.merge(MonitorAgentLiveness(server_id=server_id, last_report_at=utcnow_naive()))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Persistieren der Agent-Liveness fehlgeschlagen (%s)", server_id)


def _refuse_unstorable_report(server_id: str, report: dict) -> None:
    # A NUL anywhere in the report would die in a text column further down, a lone
    # surrogate in a tag value would fail to encode in VictoriaClient._send and take
    # the whole batch with it, lines of other servers included. Refused AFTER the
    # liveness and not on the parameter: liveness is not report content, and a
    # refused report must not turn into a "server down" alarm.
    found = find_unstorable(report)
    if found is None:
        return
    loc, value, reason = found
    logger.warning("Agent report from %s refused: %s at %s", server_id, reason, list(loc))
    raise RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", *loc),
                "msg": f"Value error, {reason}",
                "input": value,
            }
        ]
    )


def _store_host_facts(db: Session, server_id: str, report: dict) -> None:
    # No host block (an agent before R-0421) or not an object: stored facts stay.
    # Before the check loop: on failure store_host_facts rolls back the request's
    # session, which would drop check states not yet committed.
    host = report.get("host")
    if isinstance(host, dict):
        store_host_facts(db, server_id, host)


def _report_lines(server_id: str, report: dict) -> list[str]:
    ts = int(time.time())
    base_tags = {"server_id": server_id}
    lines = []

    # Values and entries are read as the checkers read them (agent_number, capped_objects,
    # entry_text): a value no check rates is no series either, and a broken list entry
    # costs only itself instead of every metric of the report (R-0632).
    try:
        resources = report.get("resources", {})
        if isinstance(resources, dict):
            for key in ("cpu_percent", "memory_percent", "load_1m", "load_5m", "load_15m"):
                val = agent_number(resources.get(key))
                if val is not None:
                    lines.append(format_line(f"monitor_agent_{key}", base_tags, val, ts))

            for disk in capped_objects(resources.get("disks")):
                if entry_text(disk, "fstype", "_real_") in EXCLUDED_FSTYPES:
                    continue
                disk_tags = {**base_tags, "mount": entry_text(disk, "mount", NO_MOUNT)}
                pct = agent_number(disk.get("percent"))
                if pct is not None:
                    lines.append(format_line("monitor_agent_disk_percent", disk_tags, pct, ts))

            for sensor in capped_objects(resources.get("temperatures")):
                temp_c = agent_number(sensor.get("temp_c"))
                if temp_c is not None and temp_c > 0:
                    sensor_tags = {**base_tags, "sensor": entry_text(sensor, "sensor", "unknown")}
                    lines.append(format_line("monitor_agent_temp", sensor_tags, temp_c, ts))

        uptime = agent_number(report.get("uptime_seconds"))
        if uptime is not None:
            lines.append(format_line("monitor_agent_uptime_seconds", base_tags, uptime, ts))

        # No SMART lines here: the smart_health checker writes monitor_smart_* with its check
        # labels, and GET /checks/{id}/metrics reads them by check_id. A copy with only
        # server_id/device was a second series nobody read (R-0633).

    except Exception:
        # Last safety net: the helpers above skip what is malformed, anything they miss
        # must only cost the metrics, not the whole request — the check evaluation is
        # already per-check isolated (4.47).
        logger.exception("Metrik-Extraktion aus Agent-Report fehlgeschlagen (%s)", server_id)
        return []
    return lines


def _push_checks(db: Session, server_id: str) -> list[MonitorCheck]:
    return (
        db.query(MonitorCheck)
        .filter(
            MonitorCheck.server_id == server_id,
            MonitorCheck.enabled == True,  # noqa: E712
            # PUSH_ONLY_TYPES is exactly the push-evaluated set. agent_ping is
            # deliberately NOT in it: this endpoint calls record_agent_report()
            # first, so the staleness age would always be ~0 ("ok") — the scheduler
            # is the single source for agent_ping.
            MonitorCheck.check_type.in_(sorted(PUSH_ONLY_TYPES)),
        )
        # Deterministic order so two concurrent pushes for this server lock the per-check state
        # rows in the same sequence — no cross-push deadlock (4.46).
        .order_by(MonitorCheck.id)
        .all()
    )


def _evaluate_push_check(
    db: Session, check: MonitorCheck, server_id: str, report: dict, now: datetime
) -> tuple[list[str], tuple[str, str, str, str] | None, tuple[str, str, str] | None]:
    """Result lines, the transition to log and the alert to send of one check.

    The SAVEPOINT carries the isolation over to a database error (a deadlock, an
    abort at FOR UPDATE, a failed flush): it would otherwise leave the shared
    transaction needing a rollback, so every following check and the commit
    failed and the whole report was lost (R-0635). The release flushes too, so
    nothing of a check is returned before its block has ended."""
    with db.begin_nested():
        config = json.loads(check.config) if check.config else {}

        # Reuse the checker registry instead of a hand-written if/elif that
        # duplicated the push-checker list across imports, the in_-filter and
        # the dispatch. The filter guarantees check_type is a push type,
        # so get_checker always resolves; each push checker implements evaluate().
        checker = get_checker(check.check_type)
        state = _locked_state(db, check.id)
        result_status, message, metrics = checker.evaluate(config, report, _prev_details(state))

        # Extract structured details
        details = metrics.pop("_details", None) if metrics else None

        result_lines = _result_lines(check, server_id, result_status, metrics)

        # Same transition pipeline as the scheduler path — one implementation
        # in check_engine, not a copy (B3). A report without a 'resources'
        # block carries no details; keeping the stored ones preserves the
        # per-metric hysteresis memory ('problems') across one degenerate
        # push (T38). notify is collected here and dispatched only after the
        # batch commit: a blocking webhook/SMTP must not stall this request.
        had_state = state is not None
        old_status, eff_status, decision = apply_result(
            db,
            check,
            state,
            result_status,
            message,
            details,
            now,
            keep_previous_details_when_absent=True,
        )

    transition = None
    if had_state and eff_status != old_status:
        transition = (check.name, old_status, eff_status, state.message)
    alert = (check.id, old_status, eff_status) if decision == "notify" else None
    return result_lines, transition, alert


def _result_lines(
    check: MonitorCheck, server_id: str, result_status: str, metrics: dict | None
) -> list[str]:
    # The status point for every evaluated check, also one without measured
    # values (system_state; Docker, ZFS or Proxmox without readable data): the
    # status timeline reads only monitor_check_status. The duration (always 0
    # here) only comes with measured values, so such a check gets no flat 0 ms
    # series.
    return victoria.build_check_result_lines(
        check_id=check.id,
        check_type=check.check_type,
        server_id=server_id,
        name=check.name,
        status=result_status,
        duration_ms=0 if metrics else None,
        extra_metrics=metrics,
    )


def _locked_state(db: Session, check_id: str) -> MonitorState | None:
    # Lock the state row BEFORE evaluating: agent_resources needs the
    # previous _details for per-metric hysteresis (T6), service_process
    # for the list mode on a push without the inventory, docker_health for
    # the restart counter per container, and the lock has to cover the
    # read-modify-write anyway — two near-simultaneous pushes must not
    # clobber fail_count or double-alert (4.46).
    # Evaluate is pure CPU, so holding the lock across it is harmless.
    # with_for_update is a no-op on sqlite (tests).
    return (
        db.query(MonitorState).filter(MonitorState.check_id == check_id).with_for_update().first()
    )


def _prev_details(state: MonitorState | None) -> dict | None:
    try:
        prev_details = json.loads(state.details) if state and state.details else None
    except (json.JSONDecodeError, TypeError):
        return None
    # Valid-but-non-dict JSON ("[]") must degrade the same way —
    # evaluate expects a mapping and the loop-except would otherwise
    # freeze this check on every push.
    return prev_details if isinstance(prev_details, dict) else None


def _commit_evaluation(db: Session, transitions: list[tuple[str, str, str, str]]) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Commit der Agent-Report-Auswertung fehlgeschlagen")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save the check evaluation",
        )
    # Logged only once saved: a transition of a check whose savepoint or the shared
    # commit failed did not happen.
    for transition in transitions:
        log_transition(*transition)
