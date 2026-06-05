# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Background scheduler for scheduled hooks.

Uses APScheduler's BackgroundScheduler (its own thread pool).
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler(timezone="UTC")

_INTERVAL_MAP = {
    "1m":  {"minutes": 1},
    "5m":  {"minutes": 5},
    "15m": {"minutes": 15},
    "30m": {"minutes": 30},
    "1h":  {"hours": 1},
    "6h":  {"hours": 6},
    "12h": {"hours": 12},
    "24h": {"hours": 24},
}


def _parse_trigger(interval: str):
    """Convert an interval string or cron expression into an APScheduler trigger."""
    if interval in _INTERVAL_MAP:
        return IntervalTrigger(**_INTERVAL_MAP[interval])
    parts = interval.split()
    if len(parts) == 5:
        return CronTrigger.from_crontab(interval)
    raise ValueError(f"Ungültiges Intervall: {interval!r}. Erlaubt: {', '.join(_INTERVAL_MAP)} oder Cron (5 Felder)")


def _execute_scheduled_hook(hook_id: str) -> None:
    from app.core.database import SessionLocal
    from app.modules.hooks.models import Hook
    from app.modules.hooks.script_runner import run_hook_script

    db = SessionLocal()
    try:
        hook = (
            db.query(Hook)
            .filter(Hook.id == hook_id, Hook.enabled == True)  # noqa: E712
            .first()
        )
        if not hook:
            return

        now = datetime.now(timezone.utc)
        last_run_str = hook.last_run.isoformat() if hook.last_run else None

        hook.last_run = now.replace(tzinfo=None)
        job = scheduler.get_job(hook_id)
        if job and job.next_run_time:
            hook.next_run = job.next_run_time.replace(tzinfo=None)
        db.commit()

        try:
            run_hook_script(
                script=hook.script,
                hook_type="schedule",
                context={"triggered_at": now.isoformat(), "last_run": last_run_str},
            )
        except Exception:
            logger.exception("Scheduled Hook '%s' fehlgeschlagen", hook.name)
    finally:
        db.close()


def add_hook(hook_id: str, interval: str) -> None:
    """Register or update a scheduled hook (replace_existing=True)."""
    trigger = _parse_trigger(interval)
    scheduler.add_job(
        _execute_scheduled_hook,
        trigger=trigger,
        id=hook_id,
        replace_existing=True,
        args=[hook_id],
    )


def remove_hook(hook_id: str) -> None:
    """Remove a scheduled hook from the scheduler."""
    if scheduler.get_job(hook_id):
        scheduler.remove_job(hook_id)


def get_next_run(hook_id: str) -> datetime | None:
    """Get the next_run_time of a registered job."""
    job = scheduler.get_job(hook_id)
    if job and job.next_run_time:
        return job.next_run_time.replace(tzinfo=None)
    return None


def load_all_scheduled_hooks() -> None:
    """On server start, load and schedule all active scheduled hooks."""
    from app.core.database import SessionLocal
    from app.modules.hooks.models import Hook

    db = SessionLocal()
    try:
        hooks = (
            db.query(Hook)
            .filter(Hook.hook_type == "schedule", Hook.enabled == True)  # noqa: E712
            .all()
        )
        for hook in hooks:
            if not hook.schedule_interval:
                continue
            try:
                add_hook(hook.id, hook.schedule_interval)
            except ValueError:
                pass

        # Update next_run in the DB
        for hook in hooks:
            next_run = get_next_run(hook.id)
            if next_run:
                hook.next_run = next_run
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# System jobs (not user-configurable)
# ---------------------------------------------------------------------------

_BLACKLIST_CLEANUP_JOB_ID = "system:blacklist-cleanup"


def _run_blacklist_cleanup() -> None:
    """Remove expired JWT blacklist entries so the token_blacklist table does
    not grow without bound."""
    from app.core.database import SessionLocal
    from app.core.auth import cleanup_expired_blacklist

    db = SessionLocal()
    try:
        removed = cleanup_expired_blacklist(db)
        if removed:
            logger.info("Blacklist-Cleanup: %d abgelaufene Eintraege entfernt", removed)
    except Exception:
        logger.exception("Blacklist-Cleanup fehlgeschlagen")
    finally:
        db.close()


def schedule_blacklist_cleanup(hours: int = 6) -> None:
    """Register a periodic system job for the blacklist cleanup (idempotent).
    Runs once immediately at start and then every `hours` hours."""
    scheduler.add_job(
        _run_blacklist_cleanup,
        trigger=IntervalTrigger(hours=hours),
        id=_BLACKLIST_CLEANUP_JOB_ID,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
