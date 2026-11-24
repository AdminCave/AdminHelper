# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Internal event bus for event hooks.

queue_event() puts an event on a session's transaction; it runs all matching active
event hooks in the background once that transaction commits, and never if it does not.
fire_event() dispatches at once, for sources without a transaction.
"""

import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="event-hook")

# Events waiting for or running on the pool. Past MAX_PENDING an event is dropped, so a
# burst or a hanging hook cannot grow the queue without bound (Kevin 2026-11-23).
MAX_PENDING = 1000
SHUTDOWN_TIMEOUT = 10.0
_pending: set[Future] = set()
_pending_lock = threading.Lock()

_QUEUED_KEY = "ah_queued_events"


def _run_event(event_type: str, event_data: Any) -> None:
    from app.core.database import SessionLocal
    from app.modules.hooks.models import Hook
    from app.modules.hooks.script_runner import (
        failed_run_error,
        notify_hook_failure,
        run_hook_script,
    )

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
                result = run_hook_script(
                    script=hook.script,
                    hook_type="event",
                    context={"event_type": event_type, "event_data": event_data or {}},
                )
                error = failed_run_error(result)
                if error is not None:
                    logger.warning(
                        "Event hook %r failed (event %s): %r", hook.name, event_type, error
                    )
                    notify_hook_failure(db, hook, f"{error} (event {event_type})")
            except Exception as exc:
                logger.exception("Event-Hook '%s' fehlgeschlagen (event=%s)", hook.name, event_type)
                notify_hook_failure(db, hook, failed_run_error({"error": repr(exc)}) or "")
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


def _release(future: Future) -> None:
    with _pending_lock:
        _pending.discard(future)


def fire_event(event_type: str, event_data: Any) -> None:
    """Dispatch the event to all matching event hooks in the thread pool, now.

    Only for sources without a transaction; a handler that commits uses queue_event.
    """
    with _pending_lock:
        if len(_pending) >= MAX_PENDING:
            logger.warning("Event queue full (%d), event %s dropped", MAX_PENDING, event_type)
            return
        future = _executor.submit(_run_event, event_type, event_data)
        _pending.add(future)
    future.add_done_callback(_release)


def queue_event(db: Session, event_type: str, event_data: Any) -> None:
    """Fire the event once db's transaction commits; a rollback or close drops it.

    Build event_data before the commit: expire_on_commit empties the objects, and no SQL
    may run where the event is dispatched.
    A SAVEPOINT rolled back does not take the event with it: only the outer transaction
    decides (app/ opens no SAVEPOINT).
    """
    # Without a transaction a rollback or close ends none, and the event would wait for
    # whatever commits next.
    if not db.in_transaction():
        db.begin()
    db.info.setdefault(_QUEUED_KEY, []).append((event_type, event_data))


@event.listens_for(Session, "after_commit")
def _dispatch_queued(session: Session) -> None:
    # A SAVEPOINT commit fires after_commit too; its events wait for the outer one.
    if session.in_nested_transaction():
        return
    for event_type, event_data in session.info.pop(_QUEUED_KEY, []):
        try:
            fire_event(event_type, event_data)
        except Exception:
            # Raised here, it would leave commit() raising for a transaction that committed.
            logger.exception("Event dispatch after commit failed (event=%s)", event_type)


@event.listens_for(Session, "after_transaction_end")
def _drop_queued(session: Session, transaction) -> None:
    # Runs after _dispatch_queued on a commit, so what is left here never committed.
    if transaction.parent is None:
        session.info.pop(_QUEUED_KEY, None)


def shutdown_events(timeout: float = SHUTDOWN_TIMEOUT) -> None:
    """Wait up to timeout for pending events; drop the ones not yet started."""
    with _pending_lock:
        pending = set(_pending)
    _, not_done = wait_futures(pending, timeout=timeout)
    dropped = sum(1 for future in not_done if future.cancel())
    if not_done:
        logger.warning(
            "Shutdown: %d event(s) unfinished after %g s, %d dropped",
            len(not_done),
            timeout,
            dropped,
        )
