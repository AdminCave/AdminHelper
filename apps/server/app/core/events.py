# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Internal event bus for event hooks.

fire_event() is called by other endpoints and runs all matching active
event hooks in the background.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="event-hook")


def _run_event(event_type: str, event_data: Any) -> None:
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
            try:
                # Parse inside the per-hook guard: a single hook row with invalid event_triggers
                # JSON (legacy data, a manual DB edit) would otherwise raise into the outer except
                # and silently skip every intact event hook after it (4.131).
                triggers = json.loads(hook.event_triggers or "[]")
                if event_type not in triggers:
                    continue
                run_hook_script(
                    script=hook.script,
                    hook_type="event",
                    context={"event_type": event_type, "event_data": event_data or {}},
                )
            except Exception:
                logger.exception("Event-Hook '%s' fehlgeschlagen (event=%s)", hook.name, event_type)
    except Exception:
        logger.exception("Event-Dispatch fehlgeschlagen (event=%s)", event_type)
    finally:
        db.close()

    # Notification bridge: fan notification-worthy events out to users. Runs
    # after (and independently of) the hook dispatch, on its own session, so a
    # hook DB error cannot suppress notifications and vice versa.
    try:
        from app.modules.notifications.event_bridge import handle_event

        handle_event(event_type, event_data)
    except Exception:
        logger.exception("Notification-Bridge fehlgeschlagen (event=%s)", event_type)


def fire_event(event_type: str, event_data: Any) -> None:
    """Dispatch the event to all matching event hooks in the thread pool."""
    _executor.submit(_run_event, event_type, event_data)
