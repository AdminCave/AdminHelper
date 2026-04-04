"""
Hintergrund-Scheduler fuer Monitoring Checks.

Eigene APScheduler-Instanz (unabhaengig vom SRM-Server).
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("monitor.scheduler")

scheduler = BackgroundScheduler(timezone="UTC")

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
    """Intervall-String oder Cron-Ausdruck in APScheduler-Trigger umwandeln."""
    if interval in _INTERVAL_MAP:
        return IntervalTrigger(**_INTERVAL_MAP[interval])
    parts = interval.split()
    if len(parts) == 5:
        return CronTrigger.from_crontab(interval)
    raise ValueError(f"Ungueltiges Intervall: {interval!r}")


def add_check(check_id: str, interval: str) -> None:
    """Check im Scheduler registrieren oder aktualisieren."""
    from app.check_engine import execute_check

    trigger = _parse_trigger(interval)
    scheduler.add_job(
        execute_check,
        trigger=trigger,
        id=f"mon_{check_id}",
        replace_existing=True,
        args=[check_id],
    )


def remove_check(check_id: str) -> None:
    """Check aus dem Scheduler entfernen."""
    job_id = f"mon_{check_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def get_next_run(check_id: str):
    """Naechsten geplanten Lauf abrufen."""
    job = scheduler.get_job(f"mon_{check_id}")
    if job and job.next_run_time:
        return job.next_run_time.replace(tzinfo=None)
    return None


def load_all_checks() -> None:
    """Beim Start alle aktiven Checks laden und einplanen."""
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
        for check in checks:
            try:
                add_check(check.id, check.interval)
                count += 1
            except ValueError as exc:
                logger.warning("Check %s (%s): %s", check.id, check.name, exc)
        logger.info("%d Monitoring-Checks geladen", count)
    finally:
        db.close()
