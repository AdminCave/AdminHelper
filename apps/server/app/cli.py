# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Internal management CLI — run inside the server container:

    docker compose exec server python -m app.cli create-admin --username U --password P
    docker compose exec server python -m app.cli reset-admin --username U --password P
    docker compose exec server python -m app.cli mint-enroll-token --username U [--ttl-minutes N]

``scripts/install.sh`` uses these to bootstrap the first admin + its enrollment
token out-of-band, so a fresh install can come up with mTLS already enforced: the
data plane ``:443`` requires a client cert, which the very first admin cannot get
through the login flow (no admin → no token → no cert → can't reach ``:443``).
The install script, running on the host with internal docker-network access,
mints the first token directly and hands it over.

The raw enrollment token is printed to **stdout** (so the script can capture it);
all human-facing messages go to **stderr**."""

from __future__ import annotations

import argparse
import datetime
import sys

# Import every model module so SQLAlchemy can resolve cross-module relationships
# (mapper configuration) before we touch the ORM — same set the test bootstrap
# imports; missing one raises "failed to locate a name" at query time.
import app.modules.ansible.models  # noqa: F401
import app.modules.api_keys.models  # noqa: F401
import app.modules.connections.models  # noqa: F401
import app.modules.enrollment.models  # noqa: F401
import app.modules.frp.models  # noqa: F401
import app.modules.hooks.models  # noqa: F401
import app.modules.servers.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from app.core.auth import hash_password
from app.core.database import SessionLocal
from app.core.identity import SCOPE_ACCESS
from app.modules.enrollment.service import mint_enrollment_token
from app.modules.notifications.service import default_admin_subscription
from app.modules.users.models import User

_MIN_PASSWORD_LEN = 8


def create_admin(db, username: str, password: str) -> int:
    """Create an admin user. Returns a process exit code (0 ok, 1 refused)."""
    if len(password) < _MIN_PASSWORD_LEN:
        print(f"Fehler: Passwort muss >= {_MIN_PASSWORD_LEN} Zeichen sein.", file=sys.stderr)
        return 1
    if db.query(User).filter(User.username == username).first() is not None:
        print(f"Fehler: Benutzer '{username}' existiert bereits.", file=sys.stderr)
        return 1
    user = User(username=username, hashed_password=hash_password(password), is_admin=True)
    db.add(user)
    # Same baseline as the API path: without a subscription no alert would
    # reach the very first admin on a fresh install.
    db.flush()
    db.add(default_admin_subscription(user.id))
    db.commit()
    print(f"Admin '{username}' angelegt.", file=sys.stderr)
    return 0


def reset_admin(db, username: str, password: str) -> int:
    """Reset an existing user's password — the recovery path for a forgotten admin
    password. Returns a process exit code (0 ok, 1 refused). create_admin refuses an
    existing user, and the API login needs the very password that is lost, so a
    locked-out admin otherwise has no way back in (8.5)."""
    if len(password) < _MIN_PASSWORD_LEN:
        print(f"Fehler: Passwort muss >= {_MIN_PASSWORD_LEN} Zeichen sein.", file=sys.stderr)
        return 1
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        print(f"Fehler: Benutzer '{username}' existiert nicht.", file=sys.stderr)
        return 1
    user.hashed_password = hash_password(password)
    db.commit()
    print(f"Passwort fuer '{username}' zurueckgesetzt.", file=sys.stderr)
    return 0


def mint_enroll_token(db, username: str, ttl_minutes: int) -> str | None:
    """Mint a one-time access enrollment token for an existing user. Returns the
    raw token, or None if the user does not exist."""
    if db.query(User).filter(User.username == username).first() is None:
        return None
    return mint_enrollment_token(
        db, username, SCOPE_ACCESS, ttl=datetime.timedelta(minutes=ttl_minutes)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="AdminHelper management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_admin = sub.add_parser("create-admin", help="Create the first admin user")
    p_admin.add_argument("--username", required=True)
    p_admin.add_argument(
        "--password",
        help="Admin password. INSECURE: visible in the process argv "
        "(/proc/<pid>/cmdline) for the duration of the call — prefer --password-stdin.",
    )
    p_admin.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from the first line of stdin (no argv leak).",
    )

    p_reset = sub.add_parser("reset-admin", help="Reset an existing user's password (recovery)")
    p_reset.add_argument("--username", required=True)
    p_reset.add_argument(
        "--password",
        help="New password. INSECURE: visible in the process argv "
        "(/proc/<pid>/cmdline) for the duration of the call — prefer --password-stdin.",
    )
    p_reset.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from the first line of stdin (no argv leak).",
    )

    p_token = sub.add_parser(
        "mint-enroll-token", help="Mint a one-time access enrollment token for a user"
    )
    p_token.add_argument("--username", required=True)
    p_token.add_argument("--ttl-minutes", type=int, default=60)

    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "create-admin":
            if args.password_stdin:
                password = sys.stdin.readline().rstrip("\n")
            else:
                password = args.password
            if not password:
                parser.error("--password or --password-stdin is required")
            return create_admin(db, args.username, password)
        if args.command == "reset-admin":
            if args.password_stdin:
                password = sys.stdin.readline().rstrip("\n")
            else:
                password = args.password
            if not password:
                parser.error("--password or --password-stdin is required")
            return reset_admin(db, args.username, password)
        if args.command == "mint-enroll-token":
            token = mint_enroll_token(db, args.username, args.ttl_minutes)
            if token is None:
                print(f"Fehler: Unbekannter Benutzer '{args.username}'.", file=sys.stderr)
                return 1
            print(token)  # stdout — captured by the install script
            return 0
    finally:
        db.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
