# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Request-scoped actor for the audit trail.

Knows *who* triggered an action (and from where). The auth dependencies bind it
once per request when they resolve the principal; audited endpoints read it back
and hand it to app.modules.audit.service.record().

Why request.state and not contextvars: FastAPI runs sync dependencies and sync
path operations in *separate* threadpool workers, each with its own copy of the
context — a contextvar set in the dependency is invisible to the endpoint. The
``request.state`` object, by contrast, is shared (it is an attribute on the one
Request instance both receive), so it survives the thread hop.
"""

from dataclasses import dataclass

from starlette.requests import Request


@dataclass(frozen=True)
class Actor:
    """Who is acting. actor_type is one of user | api_key | anonymous | system."""

    actor_type: str = "system"
    actor_id: str | None = None
    actor_label: str | None = None
    source_ip: str | None = None


_SYSTEM = Actor()


def bind_actor(request: Request, actor: Actor) -> None:
    """Bind the acting principal for this request (called by the auth deps)."""
    request.state.actor = actor


def actor_from_request(request: Request) -> Actor:
    """Return the bound actor, or a system actor if none was bound."""
    return getattr(request.state, "actor", _SYSTEM)
