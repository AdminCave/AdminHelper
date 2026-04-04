"""
Interner Event-Bus für Event-Hooks.

fire_event() wird von anderen Endpunkten aufgerufen und führt alle
passenden aktiven Event-Hooks im Hintergrund aus.
"""

import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


def fire_event(event_type: str, event_data: Any) -> None:
    """Event asynchron (Daemon-Thread) an alle passenden Event-Hooks senden."""

    def _run() -> None:
        from app.core.database import SessionLocal
        from app.modules.hooks.models import Hook
        from app.modules.hooks.script_runner import run_hook_script

        db = SessionLocal()
        try:
            hooks = (
                db.query(Hook)
                .filter(Hook.hook_type == "event", Hook.enabled == True)  # noqa: E712
                .all()
            )
            for hook in hooks:
                triggers = json.loads(hook.event_triggers or "[]")
                if event_type not in triggers:
                    continue
                try:
                    run_hook_script(
                        script=hook.script,
                        hook_type="event",
                        context={"event_type": event_type, "event_data": event_data or {}},
                    )
                except Exception:
                    logger.exception("Event-Hook '%s' fehlgeschlagen (event=%s)", hook.name, event_type)
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()
