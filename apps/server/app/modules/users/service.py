# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The one way a user comes into being: the API, the bootstrap, the CLI and the
ADMIN_PASSWORD admin at startup all call create_user, so each new user gets the
same event, audit row, notification baseline and FRP policy."""

from collections.abc import Callable, Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.events import queue_event
from app.core.request_context import Actor
from app.modules.audit import service as audit
from app.modules.frp.policy import sync_policy
from app.modules.notifications.service import default_admin_subscription
from app.modules.servers.models import Server
from app.modules.users.models import User


class UsernameTaken(Exception):
    """users.username is unique: a concurrent create of the same name won."""


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    is_admin: bool,
    actor: Actor | Callable[[User], Actor],
    servers: Iterable[Server] = (),
    audit_action: str = "user.created",
) -> User:
    """Creates and commits the user; raises UsernameTaken when the name is taken.

    ``actor`` may be a function of the new user: the bootstrap admin is its own actor,
    and its id exists only after the insert. Callers validate their input first."""
    user = User(username=username, hashed_password=hash_password(password), is_admin=is_admin)
    user.servers = list(servers)
    db.add(user)
    try:
        db.flush()
        if is_admin:
            # A fresh install has zero subscriptions, so alerts would reach
            # nobody: every new admin starts with the bell-only baseline rule.
            db.add(default_admin_subscription(user.id))
        queue_event(
            db,
            "user.created",
            {"id": user.id, "username": user.username, "is_admin": user.is_admin},
        )
        db.commit()
    except IntegrityError:
        # A pre-check by name leaves a window; the unique constraint closes it.
        # The rollback drops the queued event with the row.
        db.rollback()
        raise UsernameTaken(username) from None
    db.refresh(user)
    # A user's access is part of every STCP proxy's allowUsers, which frps' plugin checks.
    sync_policy(db)
    audit.record(
        db,
        audit_action,
        actor=actor(user) if callable(actor) else actor,
        object_type="user",
        object_id=user.id,
        object_label=user.username,
    )
    return user
