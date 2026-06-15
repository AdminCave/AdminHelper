# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Request-scoped actor context for the audit trail.

A tiny ``contextvars`` holder so audit records know *who* triggered an action
(and from where) without threading the actor through every call signature. The
auth dependencies (app.core.auth) bind it once per request when they resolve the
principal; app.modules.audit.service.record() reads it.

Lives in core because app.core.auth — itself core — populates it. Note: the
event bus (app.core.events) runs in a background thread pool and therefore does
NOT see this context; that is exactly why audit writes happen synchronously in
the request, not from an event subscriber.
"""

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    """Who is acting. actor_type is one of user | api_key | anonymous | system."""

    actor_type: str = "system"
    actor_id: str | None = None
    actor_label: str | None = None
    source_ip: str | None = None


_SYSTEM = Actor()

_current: contextvars.ContextVar[Actor] = contextvars.ContextVar("audit_actor", default=_SYSTEM)


def set_actor(actor: Actor) -> None:
    """Bind the acting principal for the current request/context."""
    _current.set(actor)


def current_actor() -> Actor:
    """Return the bound actor, or a system actor if nothing was bound."""
    return _current.get()
