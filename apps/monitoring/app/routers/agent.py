# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent push endpoint — receives metrics from remote servers."""

from __future__ import annotations

import json
import logging
import math
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.alerter import process_alert
from app.check_engine import effective_status, is_suppressed, next_fail_count
from app.check_types import PUSH_ONLY_TYPES
from app.checkers import get_checker
from app.checkers.agent import EXCLUDED_FSTYPES, record_agent_report
from app.core import database
from app.core.auth import require_agent
from app.core.database import get_db
from app.core.time import utcnow_naive
from app.core.victoria import format_line, safe_metric_part, victoria
from app.models import MonitorCheck, MonitorState

logger = logging.getLogger(__name__)

router = APIRouter()


def _dispatch_alert_bg(check_id: str, old_status: str, new_status: str) -> None:
    """Dispatch one alert (webhook/SMTP) off the agent push request path.

    Scheduled via BackgroundTasks so it runs AFTER the response: a slow or hung
    webhook/SMTP server can no longer stall the agent's request thread (at
    250-500 agents that would saturate the pool and slow the push for everyone).
    Uses its own session — the request session is already closed by the time
    this runs. Errors are contained: a failed dispatch must never surface to the
    agent. Referenced via ``database.SessionLocal`` so tests can patch it.
    """
    db = database.SessionLocal()
    try:
        check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
        if check is None:
            return
        process_alert(db, check, old_status, new_status)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Alert-Dispatch fuer Check '%s' fehlgeschlagen", check_id)
    finally:
        db.close()


def _num(v):
    """Coerce an agent-supplied metric value to int/float, else None.

    Agent values flow into the InfluxDB line protocol; a non-numeric value must
    never reach format_line (it would be a line-protocol injection vector — see
    app/core/victoria.py — and would otherwise raise/500). Numeric strings are
    accepted for leniency; anything else (incl. bool) is dropped. inf/nan are
    dropped too: written verbatim they poison the whole VictoriaMetrics batch.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else None
    if isinstance(v, str):
        try:
            num = float(v)
        except ValueError:
            return None
        return num if math.isfinite(num) else None
    return None


# Cap per-report array lengths so a compromised/misconfigured agent can't flood the
# service (a CPU/memory/VictoriaMetrics DoS) with a huge disks/temperatures/smart list.
# The body-size cap itself belongs at the gateway (client_max_body_size) (3.76).
_MAX_REPORT_ITEMS = 500


def _capped(value: object) -> list:
    """The first _MAX_REPORT_ITEMS entries of a list value, or [] for anything else
    (a non-list would otherwise iterate as chars / raise downstream)."""
    return value[:_MAX_REPORT_ITEMS] if isinstance(value, list) else []


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
            status_code=status.HTTP_403_FORBIDDEN, detail="API-Key gehoert nicht zu diesem Server"
        )

    record_agent_report(server_id)

    ts = int(time.time())
    base_tags = {"server_id": server_id}
    lines = []

    resources = report.get("resources", {})
    if resources:
        for key in ("cpu_percent", "memory_percent", "load_1m", "load_5m", "load_15m"):
            val = _num(resources.get(key))
            if val is not None:
                lines.append(format_line(f"monitor_agent_{key}", base_tags, val, ts))

        for disk in _capped(resources.get("disks")):
            if disk.get("fstype", "_real_") in EXCLUDED_FSTYPES:
                continue
            mount = disk.get("mount", "/")
            disk_tags = {**base_tags, "mount": mount}
            pct = _num(disk.get("percent"))
            if pct is not None:
                lines.append(format_line("monitor_agent_disk_percent", disk_tags, pct, ts))

        for sensor in _capped(resources.get("temperatures")):
            temp_c = _num(sensor.get("temp_c"))
            if temp_c is not None and temp_c > 0:
                sensor_tags = {**base_tags, "sensor": sensor.get("sensor", "unknown")}
                lines.append(format_line("monitor_agent_temp", sensor_tags, temp_c, ts))

    uptime = _num(report.get("uptime_seconds"))
    if uptime is not None:
        lines.append(format_line("monitor_agent_uptime_seconds", base_tags, uptime, ts))

    # SMART disk metrics
    for disk in _capped(report.get("smart")):
        device = disk.get("device", "unknown")
        # Allowlist the device id used in the (otherwise-unescaped) measurement name.
        safe_dev = safe_metric_part(device)
        smart_tags = {**base_tags, "device": device}
        dtemp = _num(disk.get("temp_c"))
        if dtemp is not None and dtemp > 0:
            lines.append(format_line(f"monitor_smart_temp_{safe_dev}", smart_tags, dtemp, ts))
        realloc = _num(disk.get("reallocated_sectors", 0))
        if realloc is not None:
            lines.append(
                format_line(f"monitor_smart_reallocated_{safe_dev}", smart_tags, realloc, ts)
            )
        pending = _num(disk.get("pending_sectors", 0))
        if pending is not None:
            lines.append(format_line(f"monitor_smart_pending_{safe_dev}", smart_tags, pending, ts))

    if lines:
        victoria.write(lines)

    # Evaluate agent-based checks for this server
    checks_updated = 0
    # (check_id, old_status, new_status) for each status change; dispatched in
    # the background after the response so webhook/SMTP never block the request.
    pending_alerts: list[tuple[str, str, str]] = []
    agent_checks = (
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
        .all()
    )

    now = utcnow_naive()

    for check in agent_checks:
        # Isolate each check: a single broken check.config (or a checker raising)
        # must not abort the evaluation of all other checks for this server
        # (same isolation as the scheduler path in check_engine.execute_check).
        try:
            config = json.loads(check.config) if check.config else {}

            # Reuse the checker registry instead of a hand-written if/elif that
            # duplicated the push-checker list across imports, the in_-filter and
            # the dispatch. The filter above guarantees check_type is a push type,
            # so get_checker always resolves; each push checker implements evaluate().
            checker = get_checker(check.check_type)
            result_status, message, metrics = checker.evaluate(config, report)

            # Extract structured details
            details = metrics.pop("_details", None) if metrics else None

            if metrics:
                victoria.write_check_result(
                    check_id=check.id,
                    check_type=check.check_type,
                    server_id=server_id,
                    name=check.name,
                    status=result_status,
                    duration_ms=0,
                    extra_metrics=metrics,
                )

            # Update state — same damping logic as the scheduler path; the
            # check_engine pure functions are the single source (audit: the
            # previous inline copy could drift from the tested implementation).
            state = db.query(MonitorState).filter(MonitorState.check_id == check.id).first()
            old_status = state.status if state else "pending"

            prev_fail_count = state.fail_count if state else 0
            new_fail_count = next_fail_count(result_status, prev_fail_count)
            eff_status = effective_status(
                result_status, new_fail_count, check.consecutive_fails, old_status
            )
            if is_suppressed(result_status, new_fail_count, check.consecutive_fails):
                message = f"{message} (Fehler {new_fail_count}/{check.consecutive_fails})"

            details_json = json.dumps(details) if details else None

            if not state:
                state = MonitorState(
                    check_id=check.id,
                    status=eff_status,
                    since=now,
                    last_check=now,
                    fail_count=new_fail_count,
                    message=message,
                    details=details_json,
                )
                db.add(state)
            else:
                if eff_status != state.status:
                    state.since = now
                state.status = eff_status
                state.fail_count = new_fail_count
                state.last_check = now
                state.message = message
                state.details = details_json

            # Alerting on status change: collect now, dispatch after the commit
            # in a background task (blocking webhook/SMTP must not stall this
            # request — see _dispatch_alert_bg).
            if old_status != eff_status:
                pending_alerts.append((check.id, old_status, eff_status))

            checks_updated += 1
        except Exception:
            logger.exception("Auswertung von Check '%s' fehlgeschlagen", check.name)
            continue

    if checks_updated:
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Commit der Agent-Report-Auswertung fehlgeschlagen")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Speichern der Check-Auswertung fehlgeschlagen",
            )

    # Only after the state is durably committed: dispatch alerts off-request.
    for check_id, old_s, new_s in pending_alerts:
        background_tasks.add_task(_dispatch_alert_bg, check_id, old_s, new_s)

    return {"status": "ok", "metricsWritten": len(lines), "checksUpdated": checks_updated}
