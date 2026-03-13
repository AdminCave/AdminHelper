"""
Interner Event-Bus für Event-Hooks.

fire_event() wird von anderen Endpunkten aufgerufen und führt alle
passenden aktiven Event-Hooks im Hintergrund aus.
"""

import json
import threading
from typing import Any


def fire_event(event_type: str, event_data: Any) -> None:
    """Event asynchron (Daemon-Thread) an alle passenden Event-Hooks senden."""

    def _run() -> None:
        from .database import SessionLocal
        from . import models
        from .script_runner import run_hook_script

        db = SessionLocal()
        try:
            hooks = (
                db.query(models.Hook)
                .filter(models.Hook.hook_type == "event", models.Hook.enabled == True)  # noqa: E712
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
                    pass
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()
