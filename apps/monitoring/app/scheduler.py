# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Background scheduler for monitoring checks.

Dedicated APScheduler instance (independent of the AdminHelper server).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.check_engine import execute_check
from app.check_types import PUSH_ONLY_TYPES
from app.core.config import ALERT_LOG_RETENTION_DAYS
from app.core.time import utcnow_naive

logger = logging.getLogger("monitor.scheduler")

# Explicit instead of APScheduler defaults (audit, target 250-500 servers):
# - misfire_grace_time: the default of 1s silently DROPS a run that starts
#   late (e.g. the pool is busy with slow HTTP/TCP checks) — 30s keeps the
#   data point instead of leaving a gap in the time series.
# - 30 workers: checks are I/O-bound (timeouts up to ~10s); the default pool
#   of 10 saturates with a few hundred scheduled checks per minute.
# - coalesce/max_instances are the defaults, pinned here as a decision:
#   several missed runs collapse into one, a check never overlaps itself.
scheduler = BackgroundScheduler(
    timezone="UTC",
    executors={"default": ThreadPoolExecutor(30)},
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 30,
    },
)

_INTERVAL_MAP = {
    "1m": {"minutes": 1},
    "5m": {"minutes": 5},
    "15m": {"minutes": 15},
    "30m": {"minutes": 30},
    "1h": {"hours": 1},
    "6h": {"hours": 6},
    "12h": {"hours": 12},
    "24h": {"hours": 24},
}


def _parse_trigger(interval: str):
    """Converts a fixed-interval string into an APScheduler trigger."""
    if interval in _INTERVAL_MAP:
        return IntervalTrigger(**_INTERVAL_MAP[interval])
    raise ValueError(f"Ungueltiges Intervall: {interval!r}. Erlaubt: {', '.join(_INTERVAL_MAP)}")


def add_check(check_id: str, interval: str, check_type: str | None) -> None:
    """Registers or updates a check in the scheduler.

    Push-only checks (agent_resources, service_process, ...) are skipped, since
    they are only evaluated on the agent report. check_type is mandatory (no
    default) so a caller can't silently schedule ghost jobs for push-only checks
    by forgetting it — the bug template_sync had (2.34).
    """
    if check_type in PUSH_ONLY_TYPES:
        # A check switched to a push-only type (via PUT) must lose any interval job
        # it had as a scheduled type, otherwise the stale job keeps firing
        # execute_check until the next restart (2.114). remove_check is idempotent,
        # so a genuinely new push-only check is unaffected.
        remove_check(check_id)
        return

    trigger = _parse_trigger(interval)
    scheduler.add_job(
        execute_check,
        trigger=trigger,
        id=f"mon_{check_id}",
        replace_existing=True,
        args=[check_id],
    )


def remove_check(check_id: str) -> None:
    """Removes a check from the scheduler (idempotent)."""
    # A parallel request (double DELETE, or a template-unassign racing a check-delete) may have
    # already removed the job between a get_job/remove_job pair, so remove_job raises
    # JobLookupError. Catch it — the job being gone IS the desired outcome (4.115).
    try:
        scheduler.remove_job(f"mon_{check_id}")
    except JobLookupError:
        pass


def load_all_checks() -> None:
    """Loads and schedules all active checks at startup."""
    from app.core.database import SessionLocal
    from app.models import MonitorCheck

    db = SessionLocal()
    try:
        checks = (
            db.query(MonitorCheck)
            .filter(MonitorCheck.enabled == True)  # noqa: E712
            .all()
        )
        count = 0
        skipped = 0
        for check in checks:
            if check.check_type in PUSH_ONLY_TYPES:
                skipped += 1
                continue
            try:
                add_check(check.id, check.interval, check.check_type)
                count += 1
            except ValueError as exc:
                logger.warning("Check %s (%s): %s", check.id, check.name, exc)
        logger.info("%d Monitoring-Checks geladen (%d Push-Only uebersprungen)", count, skipped)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# System jobs (not user-configurable)
# ---------------------------------------------------------------------------

_ALERT_LOG_CLEANUP_JOB_ID = "system:alert-log-cleanup"


def _run_alert_log_cleanup() -> None:
    """Delete alert-log entries older than the retention window so
    monitor_alert_log does not grow without bound (flapping checks write an
    entry per transition). Same pattern as the server's blacklist cleanup."""
    from app.core.database import SessionLocal
    from app.models import MonitorAlertLog

    cutoff = utcnow_naive() - timedelta(days=ALERT_LOG_RETENTION_DAYS)
    db = SessionLocal()
    try:
        removed = (
            db.query(MonitorAlertLog)
            .filter(MonitorAlertLog.sent_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        if removed:
            logger.info(
                "Alert-Log-Cleanup: %d Eintraege aelter als %d Tage entfernt",
                removed,
                ALERT_LOG_RETENTION_DAYS,
            )
    except Exception:
        db.rollback()
        logger.exception("Alert-Log-Cleanup fehlgeschlagen")
    finally:
        db.close()


def schedule_alert_log_cleanup(hours: int = 24) -> None:
    """Register the periodic alert-log cleanup (idempotent). Runs once
    immediately at start and then every `hours` hours."""
    scheduler.add_job(
        _run_alert_log_cleanup,
        trigger=IntervalTrigger(hours=hours),
        id=_ALERT_LOG_CLEANUP_JOB_ID,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )


_TAG_SYNC_JOB_ID = "system:tag-sync"


def _run_tag_sync() -> None:
    """Safety-net reconciliation of tag-based template assignments — catches
    server-notifies that were lost while the monitoring service was down.
    Imports stay function-local: tag_sync -> template_sync -> scheduler would
    otherwise be an import cycle."""
    from app.core.database import SessionLocal
    from app.tag_sync import sync_tag_assignments

    db = SessionLocal()
    try:
        sync_tag_assignments(db)
    except Exception:
        db.rollback()
        logger.exception("Tag-sync job failed")
    finally:
        db.close()


def schedule_tag_sync(minutes: int = 15) -> None:
    """Register the periodic tag-sync safety net (idempotent). First run after
    one interval — startup materialization is not needed: bindings are synced
    on CRUD and by the server's notify hook."""
    scheduler.add_job(
        _run_tag_sync,
        trigger=IntervalTrigger(minutes=minutes),
        id=_TAG_SYNC_JOB_ID,
        replace_existing=True,
    )
