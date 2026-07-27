# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check CRUD, status dashboard and metrics."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.check_configs import validate_check_config
from app.check_types import VALID_CHECK_TYPES
from app.core.auth import require_internal
from app.core.database import get_db
from app.core.pagination import paginate
from app.core.victoria import escape_label_value, victoria
from app.models import MonitorCheck, MonitorState
from app.scheduler import add_check, remove_check
from app.schemas import (
    VALID_INTERVALS,
    VALID_SEVERITIES,
    CheckCreate,
    CheckUpdate,
)

# Moved to core/victoria.py (shared with the forecast checker); alias kept so
# the existing call sites and tests stay untouched.
_escape_label = escape_label_value


def _serialize_with_states(db: Session, checks: list[MonitorCheck]) -> list[dict]:
    """Serialize checks with their current state, batch-loading the states with a
    single in_ query. Shared by the three check-listing endpoints."""
    check_ids = [c.id for c in checks]
    states = (
        {
            s.check_id: s
            for s in db.query(MonitorState).filter(MonitorState.check_id.in_(check_ids)).all()
        }
        if check_ids
        else {}
    )
    return [c.to_dict(state=states.get(c.id)) for c in checks]


router = APIRouter()

# Type-specific metrics written to VictoriaMetrics.
# VictoriaMetrics appends '_value' to InfluxDB line protocol metrics
# (measurement + '_' + field_key), hence the suffix here.
CHECK_TYPE_METRICS: dict[str, list[str]] = {
    "ping": ["monitor_check_duration_ms_value", "monitor_ping_rtt_ms_value"],
    "tcp": ["monitor_check_duration_ms_value", "monitor_tcp_connect_ms_value"],
    "http": [
        "monitor_check_duration_ms_value",
        "monitor_http_response_ms_value",
        "monitor_http_status_code_value",
    ],
    "agent_ping": ["monitor_agent_last_seen_seconds_value"],
    "agent_resources": ["monitor_agent_cpu_percent_value", "monitor_agent_memory_percent_value"],
    "service_process": [
        "monitor_services_failed_value",
        "monitor_services_enabled_inactive_value",
        "monitor_services_down_value",
        "monitor_services_up_value",
    ],
    "proxmox_backup": [
        "monitor_proxmox_backup_ok_value",
        "monitor_proxmox_backup_missing_value",
        "monitor_proxmox_backup_outdated_value",
    ],
    "zfs_health": [],  # dynamic: monitor_zfs_capacity_{pool}_value
    "docker_health": [
        "monitor_docker_ok_value",
        "monitor_docker_critical_value",
        "monitor_docker_warning_value",
    ],
    "smart_health": [
        "monitor_smart_disks_ok_value",
        "monitor_smart_disks_warning_value",
        "monitor_smart_disks_critical_value",
    ],
    "disk_forecast": [
        "monitor_check_duration_ms_value",
        "monitor_disk_forecast_min_hours_value",
    ],
}

# Check types with dynamic metric names (regex query)
_DYNAMIC_METRIC_PATTERNS: dict[str, str] = {
    "zfs_health": "monitor_zfs_capacity_.*_value",
    "agent_resources": "monitor_agent_(disk_percent|temp).*_value",
    "smart_health": "monitor_smart_(temp|reallocated|pending)_.*_value",
}


# ---------------------------------------------------------------------------
# Check CRUD
# ---------------------------------------------------------------------------


@router.get("/checks", dependencies=[Depends(require_internal)])
def list_checks(
    response: Response,
    server_id: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Lists all checks, optionally filtered by server_id."""
    q = db.query(MonitorCheck)
    if server_id:
        q = q.filter(MonitorCheck.server_id == server_id)
    checks = paginate(q.order_by(MonitorCheck.name, MonitorCheck.id), response, limit, offset).all()

    return _serialize_with_states(db, checks)


@router.post(
    "/checks", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal)]
)
def create_check(data: CheckCreate, db: Session = Depends(get_db)):
    """Creates a new check and registers it in the scheduler."""
    if data.check_type not in VALID_CHECK_TYPES:
        raise HTTPException(
            400, f"Ungueltiger check_type. Erlaubt: {', '.join(sorted(VALID_CHECK_TYPES))}"
        )
    if data.interval not in VALID_INTERVALS:
        raise HTTPException(
            400, f"Ungueltiges Intervall. Erlaubt: {', '.join(sorted(VALID_INTERVALS))}"
        )
    if data.severity not in VALID_SEVERITIES:
        raise HTTPException(
            400, f"Ungueltige Severity. Erlaubt: {', '.join(sorted(VALID_SEVERITIES))}"
        )

    check = MonitorCheck(
        id=str(uuid.uuid4()),
        server_id=data.server_id,
        name=data.name,
        description=data.description,
        check_type=data.check_type,
        config=json.dumps(data.config),
        enabled=data.enabled,
        interval=data.interval,
        severity=data.severity,
        consecutive_fails=data.consecutive_fails,
    )
    db.add(check)

    state = MonitorState(check_id=check.id, status="pending")
    db.add(state)

    db.commit()
    db.refresh(check)

    if check.enabled:
        add_check(check.id, check.interval, check.check_type)

    return check.to_dict(state=state)


@router.get("/checks/{check_id}", dependencies=[Depends(require_internal)])
def get_check(check_id: str, db: Session = Depends(get_db)):
    """Returns a single check with its state."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")
    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


@router.put("/checks/{check_id}", dependencies=[Depends(require_internal)])
def update_check(check_id: str, data: CheckUpdate, db: Session = Depends(get_db)):
    """Updates a check."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")

    sent = data.model_fields_set
    if "check_type" in sent and data.check_type not in VALID_CHECK_TYPES:
        raise HTTPException(400, "Ungueltiger check_type")
    if "interval" in sent and data.interval not in VALID_INTERVALS:
        raise HTTPException(400, "Ungueltiges Intervall")
    if "severity" in sent and data.severity not in VALID_SEVERITIES:
        raise HTTPException(400, "Ungueltige Severity")

    # Validate the effective (type, config) pair whenever either changes — a
    # type switch that keeps the old config must fail here, not surface as a
    # permanently-unknown check at runtime (see app/check_configs.py). The
    # schema can't do this: CheckUpdate doesn't know the stored type.
    if "config" in sent or "check_type" in sent:
        effective_type = data.check_type if "check_type" in sent else check.check_type
        if "config" in sent:
            effective_config = data.config
        else:
            try:
                effective_config = json.loads(check.config) if check.config else {}
            except (json.JSONDecodeError, TypeError):
                effective_config = {}
        try:
            stored_config = json.loads(check.config) if check.config else {}
        except (json.JSONDecodeError, TypeError):
            stored_config = None
        # A round-tripped, UNCHANGED config skips the strict boundary: the UI
        # resends the stored config on every edit, so re-validating it would
        # make a legacy check with a formerly-valid extra key permanently
        # uneditable (interval/severity edits included). Any actual config or
        # type change still validates strictly (T40).
        unchanged = (
            effective_type == check.check_type
            and stored_config is not None
            and effective_config == stored_config
        )
        if not unchanged:
            try:
                validate_check_config(effective_type, effective_config)
            except ValueError as exc:
                raise HTTPException(422, str(exc))

    for field in [
        "server_id",
        "name",
        "description",
        "check_type",
        "enabled",
        "interval",
        "severity",
        "consecutive_fails",
    ]:
        if field in sent:
            setattr(check, field, getattr(data, field))
    if "config" in sent:
        check.config = json.dumps(data.config)

    db.commit()
    db.refresh(check)

    if check.enabled:
        add_check(check.id, check.interval, check.check_type)
    else:
        remove_check(check.id)

    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


@router.delete(
    "/checks/{check_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal)],
)
def delete_check(check_id: str, db: Session = Depends(get_db)):
    """Deletes a check."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")

    remove_check(check.id)
    db.delete(check)
    db.commit()


@router.post("/checks/{check_id}/toggle", dependencies=[Depends(require_internal)])
def toggle_check(check_id: str, db: Session = Depends(get_db)):
    """Enables/disables a check."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")

    check.enabled = not check.enabled
    db.commit()

    if check.enabled:
        add_check(check.id, check.interval, check.check_type)
    else:
        remove_check(check.id)

    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


@router.post("/checks/{check_id}/run", dependencies=[Depends(require_internal)])
def run_check_now(check_id: str, db: Session = Depends(get_db)):
    """Runs a check immediately (manual trigger)."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")

    from app.check_engine import execute_check

    execute_check(check_id)

    db.expire_all()
    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


# ---------------------------------------------------------------------------
# Status / Dashboard
# ---------------------------------------------------------------------------


@router.get("/status", dependencies=[Depends(require_internal)])
def get_all_status(
    response: Response,
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Returns all check states for the dashboard."""
    query = db.query(MonitorCheck).order_by(MonitorCheck.name, MonitorCheck.id)
    checks = paginate(query, response, limit, offset).all()
    return _serialize_with_states(db, checks)


@router.get("/status/server/{server_id}", dependencies=[Depends(require_internal)])
def get_server_status(server_id: str, db: Session = Depends(get_db)):
    """Returns check states for a specific server."""
    checks = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.server_id == server_id)
        .order_by(MonitorCheck.name)
        .all()
    )
    return _serialize_with_states(db, checks)


@router.get("/status/summary", dependencies=[Depends(require_internal)])
def get_status_summary(db: Session = Depends(get_db)):
    """Summary: count per status. Dict response (aggregate, not a list) —
    deliberately unpaginated."""
    # Aggregate in SQL: a GROUP BY count avoids materializing every MonitorState row (incl. the
    # message/details JSON blobs) just to tally per status — thousands of rows with large text
    # columns per dashboard poll at scale (5.21).
    rows = db.query(MonitorState.status, func.count()).group_by(MonitorState.status).all()
    summary = {
        "total": 0,
        "ok": 0,
        "warning": 0,
        "critical": 0,
        "unknown": 0,
        "pending": 0,
    }
    for status_, count in rows:
        if status_ in summary:
            summary[status_] = count
        summary["total"] += count
    return summary


# ---------------------------------------------------------------------------
# Metriken (VictoriaMetrics)
# ---------------------------------------------------------------------------


@router.get("/checks/{check_id}/metrics", dependencies=[Depends(require_internal)])
def get_check_metrics(
    check_id: str,
    period: str = Query("1h", regex="^(1h|6h|24h|7d)$"),
    db: Session = Depends(get_db),
):
    """Type-specific time-series metrics + status timeline from VictoriaMetrics."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")

    period_map = {"1h": ("1h", "1m"), "6h": ("6h", "5m"), "24h": ("24h", "15m"), "7d": ("7d", "1h")}
    duration, step = period_map[period]

    all_results = []

    # Agent-based checks: query raw metrics by server_id
    # (written by the agent router without check_id)
    agent_types = {
        "agent_ping",
        "agent_resources",
        "service_process",
        "docker_health",
        "proxmox_backup",
        "zfs_health",
    }
    use_server_id = check.check_type in agent_types and check.server_id
    filter_label = (
        f'server_id="{_escape_label(check.server_id)}"'
        if use_server_id
        else f'check_id="{_escape_label(check_id)}"'
    )

    # Query all type-specific metrics in one __name__ regex range query instead of one serial
    # query_range per metric (up to 4 for e.g. service_process/http): the calls are independent, so
    # serializing them — each with a 10s httpx timeout — is pure latency on the dashboard path (5.22).
    # PromQL/VictoriaMetrics anchors the __name__ regex fully (^(...)$), and the metric names are
    # literal [a-z_] identifiers, so the |-join matches exactly those names.
    metric_names = CHECK_TYPE_METRICS.get(check.check_type, ["monitor_check_duration_ms_value"])
    if metric_names:
        # zfs_health maps to an empty list (only dynamic patterns) — skip rather than fire a
        # degenerate {__name__=~""} query, matching the old loop which ran zero times.
        names = "|".join(metric_names)
        query = f'{{__name__=~"{names}",{filter_label}}}'
        result = victoria.query_range(query=query, start=f"now-{duration}", end="now", step=step)
        all_results.extend(result.get("data", {}).get("result", []))

    # Dynamic metrics (zfs pools, disk mounts)
    pattern = _DYNAMIC_METRIC_PATTERNS.get(check.check_type)
    if pattern:
        query = f'{{__name__=~"{pattern}",{filter_label}}}'
        result = victoria.query_range(query=query, start=f"now-{duration}", end="now", step=step)
        all_results.extend(result.get("data", {}).get("result", []))

    # Status timeline (always, with _value suffix)
    status_query = f'monitor_check_status_value{{check_id="{_escape_label(check_id)}"}}'
    status_result = victoria.query_range(
        query=status_query, start=f"now-{duration}", end="now", step=step
    )

    return {
        "checkId": check_id,
        "checkType": check.check_type,
        "period": period,
        "data": all_results,
        "statusHistory": status_result.get("data", {}).get("result", []),
    }
