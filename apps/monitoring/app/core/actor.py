# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The admin behind a request, as the server's monitoring proxy names it (R-1636).

The proxy sets X-AH-Actor-Id (``<actor_type>:<actor_id>``) and X-AH-Actor-Name
(percent-encoded) from its own session and never passes a client's header on. They are
attribution for the trail of an exception, never a permission: require_internal decides
as before. Without them (internal callers, tests) the actor is empty."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote

from fastapi import HTTPException, Request

ACTOR_HEADER_MAX = 1024
ACTOR_NAME_MAX = 64


@dataclass(frozen=True)
class Actor:
    id: str | None = None
    name: str | None = None


def _header(request: Request, header: str) -> str | None:
    raw = request.headers.get(header)
    if raw is None:
        return None
    if len(raw) > ACTOR_HEADER_MAX:
        raise HTTPException(400, f"{header} is too long")
    # Control and separator characters out: the value is shown in lists and mails.
    value = "".join(c for c in unquote(raw, errors="replace") if c.isprintable())
    return value or None


def request_actor(request: Request) -> Actor:
    """The actor the proxy named for this request; empty without its headers."""
    name = _header(request, "X-AH-Actor-Name")
    return Actor(
        id=_header(request, "X-AH-Actor-Id"),
        name=name[:ACTOR_NAME_MAX] if name else None,
    )
