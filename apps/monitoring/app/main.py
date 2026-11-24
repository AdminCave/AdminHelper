# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
AdminHelper — Monitoring Service
"""

from __future__ import annotations

import datetime
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from ah_common.errors import validation_error
from ah_common.middleware import NulByteMiddleware
from ah_common.query_params import reject_repeated_scalar_query
from app.core.database import get_db
from app.core.middleware import ReportBodyLimitMiddleware
from app.models import (  # noqa: F401
    MonitorAgentKey,
    MonitorAgentLiveness,
    MonitorCheck,
    MonitorState,
    MonitorTemplate,
    MonitorTemplateAssignment,
)

logger = logging.getLogger("monitor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: bring up the scheduler. Schema creation is handled by Alembic
    (see monitoring/alembic/), no longer by Base.metadata.create_all().
    Historical SQLite PRAGMA migrations have been removed without replacement —
    pre-release, no existing data."""
    from app.builtin_templates import reconcile_builtin_templates, seed_builtin_templates
    from app.checkers.agent import hydrate_agent_liveness
    from app.core.database import SessionLocal
    from app.core.victoria import victoria
    from app.module_sync import sync_catalog
    from app.scheduler import (
        load_all_checks,
        schedule_agent_alert_bundle,
        schedule_alert_log_cleanup,
        schedule_bell_catch_up,
        schedule_history_cleanup,
        schedule_tag_sync,
        scheduler,
    )
    from app.template_sync import record_override_baseline

    # Rehydrate agent liveness before the scheduler starts: without this, every
    # restart made agent_ping report 'unknown' until the next push. Then seed
    # the built-in standard templates, mark once what users changed on template
    # checks before the update (before the first sync, which would overwrite it),
    # and move the unedited built-ins to the shipped version (tombstone-guarded,
    # best-effort — a seed failure must not keep the service down), then bring
    # adopted module instances up to the shipped catalog. All before
    # load_all_checks, which schedules what they sync.
    db = SessionLocal()
    try:
        hydrate_agent_liveness(
            {row.server_id: row.last_report_at for row in db.query(MonitorAgentLiveness).all()},
            stopped_at=db.query(func.max(MonitorState.last_check)).scalar(),
        )
        try:
            seed_builtin_templates(db)
        except Exception:
            db.rollback()
            logger.exception("Seeding der Standard-Templates fehlgeschlagen")
        try:
            record_override_baseline(db)
        except Exception:
            db.rollback()
            logger.exception("Marking the changes made before the update failed")
        try:
            reconcile_builtin_templates(db)
        except Exception:
            db.rollback()
            logger.exception("Updating the standard templates failed")
        try:
            sync_catalog(db)
        except Exception:
            db.rollback()
            logger.exception("Updating the adopted module instances failed")
    finally:
        db.close()

    load_all_checks()
    schedule_alert_log_cleanup()
    schedule_history_cleanup()
    schedule_tag_sync()
    schedule_agent_alert_bundle()
    schedule_bell_catch_up()
    # INVARIANT: exactly one worker process. This APScheduler and the in-memory
    # _last_report map (checkers/agent.py) are process-local — running uvicorn with
    # --workers > 1 would run every scheduled check + alert N times and split agent
    # pushes across processes (agent_ping would then see false staleness). The
    # entrypoint starts uvicorn without --workers; scale by running more
    # single-worker monitoring instances, not more workers per instance.
    scheduler.start()
    logger.info("Scheduler gestartet")

    yield

    scheduler.shutdown(wait=False)
    logger.info("Scheduler gestoppt")
    victoria.close()


# The monitoring service is internal-only (reached via the server's
# /api/monitoring proxy). Interactive docs + the OpenAPI schema stay off unless
# explicitly enabled for local development — both must be gated, since docs_url
# alone still serves /openapi.json.
_DOCS_ENABLED = os.environ.get("MONITOR_ENABLE_DOCS", "").lower() in ("1", "true", "yes")

app = FastAPI(
    title="AdminHelper Monitoring Service",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
    lifespan=lifespan,
    dependencies=[Depends(reject_repeated_scalar_query)],
)


app.add_exception_handler(RequestValidationError, validation_error)
# Added first, so it sits inside the NUL guard, next to the routes: a BaseHTTPMiddleware
# between it and the route would turn its 413 from reading the body into a 400.
app.add_middleware(ReportBodyLimitMiddleware)
app.add_middleware(NulByteMiddleware)

from app.routers import all_routers  # noqa: E402

for _router in all_routers:
    app.include_router(_router)


@app.get("/health")
def health():
    return {"status": "ok"}


# The window mail_failed_24h counts failed alert mails in.
_MAIL_WINDOW = datetime.timedelta(hours=24)


@app.get("/health/detail")
def health_detail(db: Session = Depends(get_db)):
    """How far the scheduler is behind and how the alert mails went: numbers only, for the
    monitoring of AdminHelper itself."""
    # Neither the gateway nor the server's monitoring proxy forwards this path: only the
    # compose network and the host reach it. /health stays without the database, it is the
    # container's healthcheck.
    from app import scheduler
    from app.check_types import PUSH_ONLY_TYPES
    from app.core.time import utcnow_naive
    from app.models import MonitorAlertLog, MonitorAlertRule

    now = utcnow_naive()
    # The scheduler runs every check of an interval once within that interval, so per
    # interval its newest run tells whether the scheduler still runs that interval; one
    # check that keeps failing does not make its interval late. A check created or enabled
    # since has had no turn yet: its change counts as a run, and so does the scheduler's
    # start (scheduler.loaded_at). The latest interval is the lag; nothing to schedule is
    # no lag.
    newest = (
        db.query(
            MonitorCheck.interval,
            func.max(MonitorState.last_check),
            func.max(MonitorCheck.updated_at),
        )
        .outerjoin(MonitorState, MonitorState.check_id == MonitorCheck.id)
        .filter(MonitorCheck.enabled.is_(True), MonitorCheck.check_type.notin_(PUSH_ONLY_TYPES))
        .group_by(MonitorCheck.interval)
        .all()
    )
    lags = []
    for interval, last_run, changed in newest:
        period = scheduler.interval_timedelta(interval)
        stamps = [t for t in (last_run, changed, scheduler.loaded_at) if t is not None]
        if period is not None and stamps:
            lags.append(max(0, int((now - max(stamps) - period).total_seconds())))
    # One send writes a row per check it names: a send is its rule and its time.
    sends = (
        db.query(MonitorAlertLog.alert_rule_id, MonitorAlertLog.sent_at)
        .join(MonitorAlertRule, MonitorAlertRule.id == MonitorAlertLog.alert_rule_id)
        .filter(MonitorAlertRule.channel == "email")
    )
    failed = (
        sends.filter(
            MonitorAlertLog.success.is_(False), MonitorAlertLog.sent_at >= now - _MAIL_WINDOW
        )
        .distinct()
        .count()
    )
    last_ok = (
        db.query(func.max(MonitorAlertLog.sent_at))
        .join(MonitorAlertRule, MonitorAlertRule.id == MonitorAlertLog.alert_rule_id)
        .filter(MonitorAlertRule.channel == "email", MonitorAlertLog.success.is_(True))
        .scalar()
    )
    return {
        "status": "ok",
        "scheduler_lag_s": max(lags, default=0),
        "mail_failed_24h": failed,
        "mail_last_ok_age_s": int((now - last_ok).total_seconds()) if last_ok else None,
    }
