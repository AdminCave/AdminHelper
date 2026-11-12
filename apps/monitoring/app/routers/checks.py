# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check CRUD, status dashboard and metrics."""

from __future__ import annotations

import json
import math
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.alerter import muted_reasons
from app.check_configs import (
    CENTRAL_PAIR_SENSORS,
    CENTRAL_SENSORS,
    ProbeConfig,
    validate_check_config,
)
from app.check_types import PUSH_ONLY_TYPES, VALID_CHECK_TYPES
from app.core.auth import require_internal
from app.core.bounds import Offset
from app.core.database import get_db
from app.core.pagination import paginate
from app.core.time import iso_utc, utcnow_naive
from app.core.victoria import escape_label_value, victoria
from app.history import (
    build_series,
    compare_query,
    compare_servers,
    history_queries,
    history_window,
    server_events,
    server_maintenance,
    server_thresholds,
)
from app.models import MonitorCheck, MonitorState
from app.scheduler import add_check, interval_timedelta, remove_check
from app.schemas import (
    VALID_INTERVALS,
    VALID_SEVERITIES,
    CheckCreate,
    CheckMetricsOut,
    CheckUpdate,
    MonitorCheckOut,
    MonitorCheckStatusOut,
    ServerCompareOut,
    ServerCostsOut,
    ServerHistoryOut,
    StatusSummaryOut,
)
from app.template_sync import (
    holds_after_substitution,
    mark_overrides,
    resolve_template_check,
    tombstone_check,
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


def _serialize_status(db: Session, checks: list[MonitorCheck]) -> list[dict]:
    """The check listing of the status routes: with state and why its notifications
    are muted, so the desktop can show a suppressed problem as suppressed (R-1225)."""
    reasons = muted_reasons(db, checks, utcnow_naive())
    rows = _serialize_with_states(db, checks)
    for row in rows:
        row["mutedReason"] = reasons[row["id"]]
    return rows


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


# The parts of a probe config that say what the agent measures and where. Only a module
# of the catalog sets them; the API leaves rules, interval and timeout to the admin.
_PROBE_MEASURE = ("sensor", "target", "params", "fields", "credential", "test_object")


def _probe_measure(config) -> dict | None:
    """The measuring parts of a probe config, missing ones at their default; None for a
    config of another form."""
    if not isinstance(config, dict):
        return None
    out = {}
    for key in _PROBE_MEASURE:
        field = ProbeConfig.model_fields[key]
        out[key] = config.get(key, None if field.is_required() else field.get_default())
    return out


def _central_refused(db: Session, check_type, config, interval, server_id) -> str | None:
    """Why a central check with these effective values is refused, or None (R-1224).

    The interval must not be shorter than the sensor allows (the targets are other
    people's services), and a partner must be an agent probe of the same server
    whose sensor sees the same service.
    """
    if check_type != "central" or not isinstance(config, dict):
        return None
    name = config.get("sensor")
    sensor = CENTRAL_SENSORS.get(name) if isinstance(name, str) else None
    if sensor is None:
        # The config schema refuses an unknown sensor; a stored one stays editable and
        # the checker reports it.
        return None
    period = interval_timedelta(interval)
    if period is not None and period < interval_timedelta(sensor.min_interval):
        return f"Interval too short for sensor {name}: at least {sensor.min_interval}"
    pair_id = config.get("pair_check_id")
    if pair_id is None:
        return None
    pair = None
    if isinstance(pair_id, str) and server_id is not None:
        pair = (
            db.query(MonitorCheck)
            .filter(
                MonitorCheck.id == pair_id,
                MonitorCheck.check_type == "probe",
                MonitorCheck.server_id == server_id,
            )
            .first()
        )
    if pair is None:
        return "pair_check_id must name a probe check of the same server"
    try:
        pair_sensor = json.loads(pair.config).get("sensor") if pair.config else None
    except (json.JSONDecodeError, TypeError, AttributeError):
        pair_sensor = None
    # A stored list or dict as sensor would make the set lookup raise.
    if not isinstance(pair_sensor, str) or pair_sensor not in CENTRAL_PAIR_SENSORS:
        return "pair_check_id must name a probe check with sensor " + ", ".join(
            sorted(CENTRAL_PAIR_SENSORS)
        )
    return None


def _probe_change_refused(check: MonitorCheck, data: CheckUpdate, sent: set[str]) -> str | None:
    """Why the update would make, unmake or re-aim a probe check, or None. A probe check
    comes only from a module of the catalog (R-1252)."""
    if "check_type" in sent and (data.check_type == "probe") != (check.check_type == "probe"):
        return "A check becomes or stops being a probe only through a module of the catalog"
    if check.check_type != "probe":
        return None
    if "server_id" in sent and data.server_id != check.server_id:
        return "A probe check stays on the server of its module"
    if "config" in sent:
        try:
            stored = json.loads(check.config) if check.config else {}
        except (json.JSONDecodeError, TypeError):
            stored = None
        new, old = _probe_measure(data.config), _probe_measure(stored)
        if new is None or old is None or not _same_config(new, old):
            return (
                "Only rules, interval_s and timeout_s of a probe config can be changed; "
                "its module sets the rest"
            )
    return None


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
    # Likewise: the values of a probe stay in its details; only the status timeline is drawn.
    "probe": [],
    "central": [
        "monitor_check_duration_ms_value",
        "monitor_days_left_value",
        "monitor_lifetime_pct_value",
        "monitor_resolvers_agree_value",
        "monitor_listed_count_value",
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
    interval = data.interval
    if data.check_type == "central" and "interval" not in data.model_fields_set:
        # The general default (5m) is shorter than most sensors allow.
        interval = CENTRAL_SENSORS[data.config["sensor"]].default_interval
    if refused := _central_refused(db, data.check_type, data.config, interval, data.server_id):
        raise HTTPException(400, refused)

    check = MonitorCheck(
        id=str(uuid.uuid4()),
        server_id=data.server_id,
        name=data.name,
        description=data.description,
        check_type=data.check_type,
        config=json.dumps(data.config),
        enabled=data.enabled,
        interval=interval,
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
    if refused := _probe_change_refused(check, data, sent):
        raise HTTPException(422, refused)

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

    if sent & {"check_type", "config", "interval", "server_id"}:
        if "config" in sent:
            central_config = data.config
        else:
            try:
                central_config = json.loads(check.config) if check.config else {}
            except (json.JSONDecodeError, TypeError):
                central_config = None
        if refused := _central_refused(
            db,
            data.check_type if "check_type" in sent else check.check_type,
            central_config,
            data.interval if "interval" in sent else check.interval,
            data.server_id if "server_id" in sent else check.server_id,
        ):
            raise HTTPException(400, refused)

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
    if not holds_after_substitution(template_values, check.server_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The template's values for this server do not form a valid check",
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


@router.post(
    "/checks/{check_id}/rebaseline",
    response_model=MonitorCheckOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def rebaseline_check(check_id: str, db: Session = Depends(get_db)):
    """Forgets the addresses a central dns check has learned; its next complete run learns them anew."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check not found")
    try:
        config = json.loads(check.config) if check.config else None
    except (json.JSONDecodeError, TypeError):
        config = None
    if (
        check.check_type != "central"
        or not isinstance(config, dict)
        or config.get("sensor") != "dns"
    ):
        raise HTTPException(400, "Only a central check with sensor dns has a baseline")
    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    details = json.loads(state.details) if state is not None and state.details else None
    # A run in progress may still write the old baseline back; the next call removes it.
    if isinstance(details, dict) and "baseline" in details:
        del details["baseline"]
        state.details = json.dumps(details)
        db.commit()
    return check.to_dict(state=state)


# ---------------------------------------------------------------------------
# Status / Dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=list[MonitorCheckStatusOut],
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
    return _serialize_status(db, checks)


@router.get(
    "/status/server/{server_id}",
    response_model=list[MonitorCheckStatusOut],
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
    return _serialize_status(db, checks)


@router.get(
    "/status/summary", response_model=StatusSummaryOut, dependencies=[Depends(require_internal)]
)
def get_status_summary(db: Session = Depends(get_db)):
    """Summary: count per status, the newest result of an enabled check and the
    shortest interval of the enabled checks (null without one). Dict response
    (aggregate, not a list) — deliberately unpaginated."""
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
    enabled = MonitorCheck.enabled == True  # noqa: E712
    last_result = (
        db.query(func.max(MonitorState.last_check))
        .join(MonitorCheck, MonitorCheck.id == MonitorState.check_id)
        .filter(enabled)
        .scalar()
    )
    # interval is a string ("5m", "1h"): its SQL min() would be the lexical one, so the
    # few distinct values come back and the shortest is picked here.
    intervals = [
        interval_timedelta(interval)
        for (interval,) in db.query(MonitorCheck.interval).filter(enabled).distinct().all()
    ]
    seconds = [int(t.total_seconds()) for t in intervals if t is not None]
    summary["lastResultAt"] = iso_utc(last_result)
    summary["minIntervalS"] = min(seconds) if seconds else None
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
    period: str = Query("1h", pattern="^(1h|6h|24h|7d|30d)$"),
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

    period_map = {
        "1h": ("1h", "1m"),
        "6h": ("6h", "5m"),
        "24h": ("24h", "15m"),
        "7d": ("7d", "1h"),
        "30d": ("30d", "6h"),
    }
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


@router.get(
    "/status/server/{server_id}/history",
    response_model=ServerHistoryOut,
    dependencies=[Depends(require_internal)],
)
def get_server_history(
    server_id: str,
    period: str = Query("24h", pattern="^(1h|24h|7d|30d)$"),
    previous: bool = False,
    db: Session = Depends(get_db),
):
    """Resource history of one server from its agent: CPU, RAM, swap, load per CPU,
    network in/out and disks on one time grid, optionally the previous period, the warn/crit thresholds,
    the status changes of its checks and its maintenance windows."""
    start, end, step = history_window(period, time.time())
    thresholds = server_thresholds(db, server_id)
    events = server_events(db, server_id, start, end)
    maintenance = server_maintenance(db, server_id, start, end)
    # Up to six query_range calls follow; the connection goes back to the pool first.
    db.rollback()
    queries = history_queries(server_id, step)

    def period_series(shift: int) -> dict:
        results = [
            _series_or_502(
                victoria.query_range(
                    query=queries[kind],
                    start=str(start - shift),
                    end=str(end - shift),
                    step=f"{step}s",
                )
            )
            for kind in ("usage", "load", "net")
        ]
        return build_series(*results, start, end, step, shift)

    return {
        "serverId": server_id,
        "period": period,
        "step": step,
        "start": start,
        "end": end,
        "series": period_series(0),
        "previous": period_series(end - start) if previous else None,
        "thresholds": thresholds,
        "events": events,
        "maintenance": maintenance,
    }


# The agent's self-measurement per collector (R-1223, routers/agent.py _collector_lines).
_COST_FIELDS = {
    "monitor_agent_collector_duration_ms_value": "durationMs",
    "monitor_agent_collector_cpu_ms_value": "cpuMs",
    "monitor_agent_collector_factor_value": "factor",
    "monitor_agent_collector_throttled_value": "throttled",
}


_COST_MEAN = "monitor_agent_collector_(duration_ms|cpu_ms)_value"
_COST_LAST = "monitor_agent_collector_(factor|throttled)_value"


def _cost_queries(server_id: str) -> dict[str, str]:
    """Mean duration and CPU time of a run, the time-limit hits (a count per run, so
    summed) and the newest factor and throttle flag, each over the last hour."""
    labels = f'server_id="{_escape_label(server_id)}"'
    return {
        "mean": f'avg_over_time({{__name__=~"{_COST_MEAN}",{labels}}}[1h]) keep_metric_names',
        "timeouts": f"sum_over_time(monitor_agent_collector_timeouts_value{{{labels}}}[1h])",
        "last": f'last_over_time({{__name__=~"{_COST_LAST}",{labels}}}[1h]) keep_metric_names',
    }


def _last_points(result: list) -> list[tuple[dict, float]]:
    """(labels, value) of the newest finite point of each series."""
    points = []
    for series in result:
        values = series.get("values") or []
        try:
            value = float(values[-1][1])
        except (IndexError, TypeError, ValueError):
            continue
        if math.isfinite(value):
            points.append((series.get("metric") or {}, value))
    return points


@router.get(
    "/status/server/{server_id}/costs",
    response_model=ServerCostsOut,
    dependencies=[Depends(require_internal)],
)
def get_server_costs(server_id: str):
    """What monitoring costs one server, per agent collector over the last hour: mean
    duration and CPU time of a run, the time-limit hits, the current factor and whether
    the agent throttles the collector."""
    end = int(time.time())
    collectors: dict[str, dict] = {}
    for kind, query in _cost_queries(server_id).items():
        # The newest point of a short range stands for the hour before it.
        result = _series_or_502(
            victoria.query_range(query=query, start=str(end - 300), end=str(end), step="60s")
        )
        for labels, value in _last_points(result):
            name = labels.get("collector")
            if not name:
                continue
            entry = collectors.setdefault(
                name,
                {
                    "collector": name,
                    "durationMs": None,
                    "cpuMs": None,
                    "timeouts": None,
                    "factor": None,
                    "throttled": None,
                },
            )
            field = "timeouts" if kind == "timeouts" else _COST_FIELDS.get(labels.get("__name__"))
            if field == "throttled":
                entry[field] = value != 0
            elif field:
                entry[field] = value
    return {
        "serverId": server_id,
        "window": "1h",
        "collectors": [collectors[name] for name in sorted(collectors)],
    }


@router.get(
    "/status/compare",
    response_model=ServerCompareOut,
    dependencies=[Depends(require_internal)],
)
def get_status_compare(
    metric: str = Query(..., pattern="^(cpu|ram|disk|load|net)$"),
    period: str = Query("24h", pattern="^(1h|24h|7d|30d)$"),
):
    """One metric of every server with agent data on the history grid: CPU, RAM, the
    fullest disk, load per CPU or incoming network traffic."""
    start, end, step = history_window(period, time.time())
    result = _series_or_502(
        victoria.query_range(
            query=compare_query(metric, step), start=str(start), end=str(end), step=f"{step}s"
        )
    )
    return {
        "metric": metric,
        "period": period,
        "step": step,
        "start": start,
        "end": end,
        "servers": compare_servers(result, start, end, step),
    }
