# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent push endpoint — receives metrics from remote servers."""

from __future__ import annotations

import json
import re
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.alerter import process_alert
from app.checkers.agent import EXCLUDED_FSTYPES
from app.core.auth import require_agent
from app.core.database import get_db
from app.core.victoria import victoria, format_line
from app.models import MonitorCheck, MonitorState

logger = logging.getLogger(__name__)

router = APIRouter()


def _num(v):
    """Coerce an agent-supplied metric value to int/float, else None.

    Agent values flow into the InfluxDB line protocol; a non-numeric value must
    never reach format_line (it would be a line-protocol injection vector — see
    app/core/victoria.py — and would otherwise raise/500). Numeric strings are
    accepted for leniency; anything else (incl. bool) is dropped.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


@router.post("/agent/{server_id}/report")
def agent_report(server_id: str, report: dict, db: Session = Depends(get_db), auth_server_id: str = Depends(require_agent)):
    """Agent pushes metrics directly to the monitoring service."""
    if auth_server_id != "__internal__" and auth_server_id != server_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API-Key gehoert nicht zu diesem Server")

    import time as _time
    from app.checkers.agent import AgentResourcesChecker, ServiceProcessChecker, record_agent_report
    from app.checkers.plugins import ProxmoxBackupChecker, ZfsHealthChecker, DockerHealthChecker
    from app.checkers.smart import SmartHealthChecker

    record_agent_report(server_id)

    ts = int(_time.time())
    base_tags = {"server_id": server_id}
    lines = []

    resources = report.get("resources", {})
    if resources:
        for key in ("cpu_percent", "memory_percent", "load_1m", "load_5m", "load_15m"):
            val = _num(resources.get(key))
            if val is not None:
                lines.append(format_line(f"monitor_agent_{key}", base_tags, val, ts))

        for disk in resources.get("disks", []):
            if disk.get("fstype", "_real_") in EXCLUDED_FSTYPES:
                continue
            mount = disk.get("mount", "/")
            disk_tags = {**base_tags, "mount": mount}
            pct = _num(disk.get("percent"))
            if pct is not None:
                lines.append(format_line("monitor_agent_disk_percent", disk_tags, pct, ts))

        for sensor in resources.get("temperatures", []):
            temp_c = _num(sensor.get("temp_c"))
            if temp_c is not None and temp_c > 0:
                sensor_tags = {**base_tags, "sensor": sensor.get("sensor", "unknown")}
                lines.append(format_line("monitor_agent_temp", sensor_tags, temp_c, ts))

    uptime = _num(report.get("uptime_seconds"))
    if uptime is not None:
        lines.append(format_line("monitor_agent_uptime_seconds", base_tags, uptime, ts))

    # SMART disk metrics
    for disk in report.get("smart", []):
        device = disk.get("device", "unknown")
        # Allowlist the device id used in the (otherwise-unescaped) measurement name.
        safe_dev = re.sub(r"[^A-Za-z0-9_]", "_", str(device)).strip("_") or "unknown"
        smart_tags = {**base_tags, "device": device}
        dtemp = _num(disk.get("temp_c"))
        if dtemp is not None and dtemp > 0:
            lines.append(format_line(f"monitor_smart_temp_{safe_dev}", smart_tags, dtemp, ts))
        realloc = _num(disk.get("reallocated_sectors", 0))
        if realloc is not None:
            lines.append(format_line(f"monitor_smart_reallocated_{safe_dev}", smart_tags, realloc, ts))
        pending = _num(disk.get("pending_sectors", 0))
        if pending is not None:
            lines.append(format_line(f"monitor_smart_pending_{safe_dev}", smart_tags, pending, ts))

    if lines:
        victoria.write(lines)

    # Evaluate agent-based checks for this server
    checks_updated = 0
    agent_checks = (
        db.query(MonitorCheck)
        .filter(
            MonitorCheck.server_id == server_id,
            MonitorCheck.enabled == True,  # noqa: E712
            MonitorCheck.check_type.in_(["agent_ping", "agent_resources", "service_process",
                                        "proxmox_backup", "zfs_health", "docker_health",
                                        "smart_health"]),
        )
        .all()
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for check in agent_checks:
        config = json.loads(check.config) if check.config else {}

        if check.check_type == "agent_ping":
            from app.checkers.agent import AgentPingChecker
            result_status, message, metrics = AgentPingChecker().run(config)
        elif check.check_type == "agent_resources":
            result_status, message, metrics = AgentResourcesChecker().evaluate(config, report)
        elif check.check_type == "service_process":
            result_status, message, metrics = ServiceProcessChecker().evaluate(config, report)
        elif check.check_type == "proxmox_backup":
            result_status, message, metrics = ProxmoxBackupChecker().evaluate(config, report)
        elif check.check_type == "zfs_health":
            result_status, message, metrics = ZfsHealthChecker().evaluate(config, report)
        elif check.check_type == "docker_health":
            result_status, message, metrics = DockerHealthChecker().evaluate(config, report)
        elif check.check_type == "smart_health":
            result_status, message, metrics = SmartHealthChecker().evaluate(config, report)
        else:
            continue

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

        # Update state
        state = db.query(MonitorState).filter(MonitorState.check_id == check.id).first()
        old_status = state.status if state else "pending"

        if result_status != "ok":
            new_fail_count = (state.fail_count + 1) if state else 1
        else:
            new_fail_count = 0

        if result_status != "ok" and new_fail_count < check.consecutive_fails:
            effective_status = old_status if old_status != "pending" else "ok"
        else:
            effective_status = result_status

        details_json = json.dumps(details) if details else None

        if not state:
            state = MonitorState(
                check_id=check.id, status=effective_status, since=now,
                last_check=now, fail_count=new_fail_count, message=message,
                details=details_json,
            )
            db.add(state)
        else:
            if effective_status != state.status:
                state.since = now
            state.status = effective_status
            state.fail_count = new_fail_count
            state.last_check = now
            state.message = message
            state.details = details_json

        # Alerting on status change
        if old_status != effective_status:
            try:
                process_alert(db, check, old_status, effective_status)
            except Exception:
                logger.exception("Alerting fuer Check '%s' fehlgeschlagen", check.name)

        checks_updated += 1

    if checks_updated:
        db.commit()

    return {"status": "ok", "metricsWritten": len(lines), "checksUpdated": checks_updated}
