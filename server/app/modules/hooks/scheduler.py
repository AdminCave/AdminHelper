"""
Hintergrund-Scheduler für Scheduled Hooks.

Verwendet APScheduler BackgroundScheduler (eigener Thread-Pool).
"""

from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler(timezone="UTC")

_INTERVAL_MAP = {
    "5m":  {"minutes": 5},
    "15m": {"minutes": 15},
    "30m": {"minutes": 30},
    "1h":  {"hours": 1},
    "6h":  {"hours": 6},
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
            pass
    finally:
        db.close()


def add_hook(hook_id: str, interval: str) -> None:
    """Scheduled Hook registrieren oder aktualisieren (replace_existing=True)."""
    trigger = _parse_trigger(interval)
    scheduler.add_job(
        _execute_scheduled_hook,
        trigger=trigger,
        id=hook_id,
        replace_existing=True,
        args=[hook_id],
    )


def remove_hook(hook_id: str) -> None:
    """Scheduled Hook aus dem Scheduler entfernen."""
    if scheduler.get_job(hook_id):
        scheduler.remove_job(hook_id)


def get_next_run(hook_id: str) -> datetime | None:
    """next_run_time eines registrierten Jobs abrufen."""
    job = scheduler.get_job(hook_id)
    if job and job.next_run_time:
        return job.next_run_time.replace(tzinfo=None)
    return None


def load_all_scheduled_hooks() -> None:
    """Beim Server-Start alle aktiven Scheduled Hooks laden und einplanen."""
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

        # next_run in DB aktualisieren
        for hook in hooks:
            next_run = get_next_run(hook.id)
            if next_run:
                hook.next_run = next_run
        db.commit()
    finally:
        db.close()
