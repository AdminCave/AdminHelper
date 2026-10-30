# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check CRUD, status dashboard and metrics."""

from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.check_configs import validate_check_config
from app.check_types import PUSH_ONLY_TYPES, VALID_CHECK_TYPES
from app.core.auth import require_internal
from app.core.bounds import Offset
from app.core.database import get_db
from app.core.pagination import paginate
from app.core.victoria import escape_label_value, victoria
from app.models import MonitorCheck, MonitorState
from app.scheduler import add_check, remove_check
from app.schemas import (
    VALID_INTERVALS,
    VALID_SEVERITIES,
    CheckCreate,
    CheckMetricsOut,
    CheckUpdate,
    MonitorCheckOut,
    StatusSummaryOut,
)
from app.template_sync import mark_overrides, resolve_template_check, tombstone_check

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


def _schedule(check: MonitorCheck) -> None:
    """Brings the running scheduler in line with a committed check."""
    if check.enabled:
        add_check(check.id, check.interval, check.check_type)
    else:
        remove_check(check.id)


def _same_config(a, b) -> bool:
    """== on parsed JSON, except that a bool never equals a number: 0 == False would
    let a 0 sent for a stored false count as unchanged and skip the strict boundary.
    Numbers still compare by value (26 == 26.0)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same_config(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same_config(x, y) for x, y in zip(a, b))
    return a == b


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
    # No measured values, only the status timeline; without the entry the fallback would
    # ask for monitor_check_duration_ms, which the push path does not write for it.
    "system_state": [],
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


@router.get(
    "/checks",
    response_model=list[MonitorCheckOut],
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def list_checks(
    response: Response,
    server_id: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: Annotated[Offset, Query()] = 0,
    db: Session = Depends(get_db),
):
    """Lists all checks, optionally filtered by server_id."""
    q = db.query(MonitorCheck)
    if server_id:
        q = q.filter(MonitorCheck.server_id == server_id)
    checks = paginate(q.order_by(MonitorCheck.name, MonitorCheck.id), response, limit, offset).all()

    return _serialize_with_states(db, checks)


@router.post(
    "/checks",
    status_code=status.HTTP_201_CREATED,
    response_model=MonitorCheckOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def create_check(data: CheckCreate, db: Session = Depends(get_db)):
    """Creates a new check and registers it in the scheduler."""
    if data.check_type not in VALID_CHECK_TYPES:
        raise HTTPException(
            400, f"Invalid check_type. Allowed: {', '.join(sorted(VALID_CHECK_TYPES))}"
        )
    if data.interval not in VALID_INTERVALS:
        raise HTTPException(400, f"Invalid interval. Allowed: {', '.join(sorted(VALID_INTERVALS))}")
    if data.severity not in VALID_SEVERITIES:
        raise HTTPException(
            400, f"Invalid severity. Allowed: {', '.join(sorted(VALID_SEVERITIES))}"
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
        consecutive_oks=data.consecutive_oks,
    )
    db.add(check)

    state = MonitorState(check_id=check.id, status="pending")
    db.add(state)

    db.commit()
    db.refresh(check)

    _schedule(check)

    return check.to_dict(state=state)


@router.get(
    "/checks/{check_id}",
    response_model=MonitorCheckOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def get_check(check_id: str, db: Session = Depends(get_db)):
    """Returns a single check with its state."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")
    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


@router.put(
    "/checks/{check_id}",
    response_model=MonitorCheckOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def update_check(check_id: str, data: CheckUpdate, db: Session = Depends(get_db)):
    """Updates a check."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")

    sent = data.model_fields_set
    if "check_type" in sent and data.check_type not in VALID_CHECK_TYPES:
        raise HTTPException(400, "Invalid check_type")
    if "interval" in sent and data.interval not in VALID_INTERVALS:
        raise HTTPException(400, "Invalid interval")
    if "severity" in sent and data.severity not in VALID_SEVERITIES:
        raise HTTPException(400, "Invalid severity")

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
            and _same_config(effective_config, stored_config)
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
        "consecutive_oks",
    ]:
        if field in sent:
            setattr(check, field, getattr(data, field))
    if "config" in sent:
        check.config = json.dumps(data.config)
    mark_overrides(db, check, {field: getattr(data, field) for field in sent})

    db.commit()
    db.refresh(check)

    _schedule(check)

    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


@router.delete(
    "/checks/{check_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal)],
)
def delete_check(check_id: str, db: Session = Depends(get_db)):
    """Deletes a check. A template check stays deleted on the next template sync."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")

    tombstone_check(db, check)
    db.delete(check)
    db.commit()
    # Only now: if the commit fails, the check stays and its job must keep running.
    remove_check(check_id)


@router.post(
    "/checks/{check_id}/toggle",
    response_model=MonitorCheckOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def toggle_check(check_id: str, db: Session = Depends(get_db)):
    """Enables/disables a check."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")

    check.enabled = not check.enabled
    mark_overrides(db, check, {"enabled": check.enabled})
    db.commit()

    _schedule(check)

    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


@router.post(
    "/checks/{check_id}/reset",
    response_model=MonitorCheckOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def reset_check(check_id: str, db: Session = Depends(get_db)):
    """Drops the user's changes to a template check: every template field gets
    the template's value again."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")
    if not check.template_id or not check.template_def_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Check was not created by a template")
    template_values = resolve_template_check(db, check)
    if template_values is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The check's template no longer defines it for this server"
        )

    for field, value in template_values.items():
        setattr(check, field, json.dumps(value) if field == "config" else value)
    check.overridden_fields = "[]"
    db.commit()
    db.refresh(check)

    _schedule(check)

    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


@router.post(
    "/checks/{check_id}/run",
    response_model=MonitorCheckOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def run_check_now(check_id: str, db: Session = Depends(get_db)):
    """Runs a check immediately (manual trigger)."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")

    # execute_check bails out silently for both cases (the enabled filter and the
    # push-only return). Without this guard the endpoint still answered 200 with an
    # unchanged state — indistinguishable from "ran, nothing changed".
    if check.check_type in PUSH_ONLY_TYPES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Check type '{check.check_type}' is evaluated only from the agent push "
            "and cannot be triggered manually",
        )
    if not check.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Check is disabled")

    from app.check_engine import execute_check

    # The run takes up to the check's timeout and execute_check opens its own session;
    # the request's connection goes back to the pool first (R-0615).
    db.rollback()
    execute_check(check_id)

    # The rollback above expired `check`; a check deleted during the run is gone now.
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")
    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


# ---------------------------------------------------------------------------
# Status / Dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=list[MonitorCheckOut],
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def get_all_status(
    response: Response,
    limit: int | None = Query(None, ge=1, le=1000),
    offset: Annotated[Offset, Query()] = 0,
    db: Session = Depends(get_db),
):
    """Returns all check states for the dashboard."""
    query = db.query(MonitorCheck).order_by(MonitorCheck.name, MonitorCheck.id)
    checks = paginate(query, response, limit, offset).all()
    return _serialize_with_states(db, checks)


@router.get(
    "/status/server/{server_id}",
    response_model=list[MonitorCheckOut],
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def get_server_status(server_id: str, db: Session = Depends(get_db)):
    """Returns check states for a specific server."""
    checks = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.server_id == server_id)
        .order_by(MonitorCheck.name)
        .all()
    )
    return _serialize_with_states(db, checks)


@router.get(
    "/status/summary", response_model=StatusSummaryOut, dependencies=[Depends(require_internal)]
)
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


def _series_or_502(response: dict) -> list:
    """The series of a query_range response, or 502 if the query failed.

    query_range answers every failure with status "error" and an empty result; read as
    series, a dead VictoriaMetrics would look like "no data" (R-0636). The first failed
    query ends the request: no partial chart, no further 10 s wait."""
    if response.get("status") == "error":
        raise HTTPException(502, "Metrics store unavailable")
    return response.get("data", {}).get("result", [])


@router.get(
    "/checks/{check_id}/metrics",
    response_model=CheckMetricsOut,
    dependencies=[Depends(require_internal)],
)
def get_check_metrics(
    check_id: str,
    period: str = Query("1h", pattern="^(1h|6h|24h|7d)$"),
    db: Session = Depends(get_db),
):
    """Type-specific time-series metrics + status timeline from VictoriaMetrics."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")
    check_type, server_id = check.check_type, check.server_id
    # Up to three query_range calls of up to 10 s each follow; the request's connection
    # goes back to the pool before them (R-0615).
    db.rollback()

    period_map = {"1h": ("1h", "1m"), "6h": ("6h", "5m"), "24h": ("24h", "15m"), "7d": ("7d", "1h")}
    duration, step = period_map[period]

    all_results = []

    # agent_resources is the one type read by server: the agent push writes CPU, RAM,
    # disks and temperatures per server without check_id (routers/agent.py). Every other
    # type, push or pull, writes its values through its check result with the check's
    # labels (build_check_result_lines), so two checks of one type on one server read
    # only their own series (R-0749).
    if check_type == "agent_resources" and server_id:
        # Only the push handler's series, which carry no check_id: CPU/RAM copies the
        # checker wrote with its check labels stay in VictoriaMetrics until the retention
        # ends and would come back as a second series of the same name (R-0633).
        # label="" selects the series without that label (Prometheus semantics, probed
        # against the pinned VictoriaMetrics image).
        filter_label = f'server_id="{_escape_label(server_id)}",check_id=""'
    else:
        filter_label = f'check_id="{_escape_label(check_id)}"'

    # Query all type-specific metrics in one __name__ regex range query instead of one serial
    # query_range per metric (up to 4 for e.g. service_process/http): the calls are independent, so
    # serializing them — each with a 10s httpx timeout — is pure latency on the dashboard path (5.22).
    # PromQL/VictoriaMetrics anchors the __name__ regex fully (^(...)$), and the metric names are
    # literal [a-z_] identifiers, so the |-join matches exactly those names.
    metric_names = CHECK_TYPE_METRICS.get(check_type, ["monitor_check_duration_ms_value"])
    if metric_names:
        # zfs_health maps to an empty list (only dynamic patterns) — skip rather than fire a
        # degenerate {__name__=~""} query, matching the old loop which ran zero times.
        names = "|".join(metric_names)
        query = f'{{__name__=~"{names}",{filter_label}}}'
        result = victoria.query_range(query=query, start=f"now-{duration}", end="now", step=step)
        all_results.extend(_series_or_502(result))

    # Dynamic metrics (zfs pools, disk mounts)
    pattern = _DYNAMIC_METRIC_PATTERNS.get(check_type)
    if pattern:
        query = f'{{__name__=~"{pattern}",{filter_label}}}'
        result = victoria.query_range(query=query, start=f"now-{duration}", end="now", step=step)
        all_results.extend(_series_or_502(result))

    # Status timeline (always, with _value suffix)
    status_query = f'monitor_check_status_value{{check_id="{_escape_label(check_id)}"}}'
    status_result = victoria.query_range(
        query=status_query, start=f"now-{duration}", end="now", step=step
    )

    return {
        "checkId": check_id,
        "checkType": check_type,
        "period": period,
        "data": all_results,
        "statusHistory": _series_or_502(status_result),
    }
