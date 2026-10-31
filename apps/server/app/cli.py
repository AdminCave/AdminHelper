# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Internal management CLI — run inside the server container:

    printf '%s\\n' "$PW" | docker compose exec -T server \\
        python -m app.cli create-admin --username U --password-stdin
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
import fcntl
import os
import sys
from typing import NoReturn

# Every ORM model before the first query, see app/model_registry.py.
from app import model_registry  # noqa: F401
from app.core.auth import hash_password
from app.core.database import SessionLocal
from app.core.events import fire_event
from app.core.identity import SCOPE_ACCESS
from app.core.request_context import Actor
from app.core.time import utcnow_naive
from app.modules.audit import service as audit
from app.modules.enrollment.service import mint_enrollment_token
from app.modules.notifications.service import default_admin_subscription
from app.modules.users.models import User
from app.modules.users.schemas import PASSWORD_MAX_LEN

_MIN_PASSWORD_LEN = 8
# No request, no principal: the operator at the container shell. The web panel
# lists these rows under the actor filter `system`.
_CLI_ACTOR = Actor("system", None, "cli", None)


def create_admin(db, username: str, password: str) -> int:
    """Create an admin user. Returns a process exit code (0 ok, 1 refused)."""
    if len(password) < _MIN_PASSWORD_LEN:
        print(f"Fehler: Passwort muss >= {_MIN_PASSWORD_LEN} Zeichen sein.", file=sys.stderr)
        return 1
    if len(password) > PASSWORD_MAX_LEN:
        print(
            f"Error: the password must be at most {PASSWORD_MAX_LEN} characters.", file=sys.stderr
        )
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
    # Not lost when the CLI exits right after: concurrent.futures registers a join
    # of its worker threads at interpreter shutdown, so the hooks and the
    # notification bridge still run before the process ends.
    fire_event("user.created", {"id": user.id, "username": user.username, "is_admin": True})
    audit.record(
        db,
        "user.created",
        actor=_CLI_ACTOR,
        object_type="user",
        object_id=user.id,
        object_label=user.username,
    )
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
    if len(password) > PASSWORD_MAX_LEN:
        print(
            f"Error: the password must be at most {PASSWORD_MAX_LEN} characters.", file=sys.stderr
        )
        return 1
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        print(f"Fehler: Benutzer '{username}' existiert nicht.", file=sys.stderr)
        return 1
    user.hashed_password = hash_password(password)
    # Like a password change over the API: tokens issued before the reset no
    # longer authenticate (core/auth.py).
    user.tokens_valid_after = utcnow_naive()
    db.commit()
    audit.record(
        db,
        "user.password_reset",
        actor=_CLI_ACTOR,
        object_type="user",
        object_id=user.id,
        object_label=user.username,
    )
    print(f"Passwort fuer '{username}' zurueckgesetzt.", file=sys.stderr)
    return 0


def mint_enroll_token(db, username: str, ttl_minutes: int) -> str | None:
    """Mint a one-time access enrollment token for an existing user. Returns the
    raw token, or None if the user does not exist."""
    if db.query(User).filter(User.username == username).first() is None:
        return None
    token = mint_enrollment_token(
        db, username, SCOPE_ACCESS, ttl=datetime.timedelta(minutes=ttl_minutes)
    )
    audit.record(
        db,
        "enrollment.token.minted_for",
        actor=_CLI_ACTOR,
        object_type="user",
        object_id=username,
    )
    return token


def _restart_with_password_on_stdin(
    parser: argparse.ArgumentParser, username: str, password: str
) -> NoReturn:
    """Replace this process by ``create-admin --password-stdin`` with the password
    of --password on stdin.

    create_admin fires ``user.created``, and the event hooks run in the CLI process
    and its child processes. With --password the password is in this process's
    command line (/proc/<pid>/cmdline) for as long as it runs; the new process reads
    it the way --password-stdin does, so it is out of the command line before the
    user is created."""
    if "\n" in password:
        parser.error("--password must not contain a newline")
    data = os.fsencode(password) + b"\n"
    read_end, write_end = os.pipe()
    # Written before the exec, with no reader yet: it has to fit into the pipe.
    if len(data) > fcntl.fcntl(write_end, fcntl.F_GETPIPE_SZ):
        os.close(read_end)
        os.close(write_end)
        parser.error("--password is too long, use --password-stdin")
    with os.fdopen(write_end, "wb") as pipe:
        pipe.write(data)
    # The pipe's fds are close-on-exec, fd 0 has to survive the exec. With fd 0
    # closed at the start (`<&-`), os.pipe() hands out 0 itself and dup2(0, 0)
    # would leave the flag set.
    if read_end == 0:
        os.set_inheritable(0, True)
    else:
        os.dup2(read_end, 0)
    # The = form: a username that starts with "-" stays a value for argparse.
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "app.cli",
            "create-admin",
            f"--username={username}",
            "--password-stdin",
        ],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="AdminHelper management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_admin = sub.add_parser("create-admin", help="Create the first admin user")
    p_admin.add_argument("--username", required=True)
    # Exclusive: with both, --password would stay in argv, as the restart only fires without
    # --password-stdin.
    admin_pw = p_admin.add_mutually_exclusive_group()
    admin_pw.add_argument(
        "--password",
        help="Admin password. Visible in the process argv (/proc/<pid>/cmdline) until the "
        "CLI hands it over stdin to a fresh process, before the user is created — prefer "
        "--password-stdin.",
    )
    admin_pw.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from the first line of stdin (no argv leak).",
    )

    p_reset = sub.add_parser("reset-admin", help="Reset an existing user's password (recovery)")
    p_reset.add_argument("--username", required=True)
    reset_pw = p_reset.add_mutually_exclusive_group()
    reset_pw.add_argument(
        "--password",
        help="New password. INSECURE: visible in the process argv "
        "(/proc/<pid>/cmdline) for the duration of the call — prefer --password-stdin.",
    )
    reset_pw.add_argument(
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
    # Only the real call: main([...]) inside a process (tests) has no password in
    # the command line, and an exec would replace its caller.
    if (
        argv is None
        and args.command == "create-admin"
        and args.password
        and not args.password_stdin
    ):
        _restart_with_password_on_stdin(parser, args.username, args.password)

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
