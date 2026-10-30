# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Management CLI (`app.cli`): the install-time bootstrap of the first admin +
its enrollment token, so a fresh deployment can come up with mTLS enforced."""

from __future__ import annotations

import fcntl
import io
import json
import os
import subprocess
import sys
import time
from concurrent.futures import Future
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.cli as cli
from app.cli import create_admin, mint_enroll_token, reset_admin
from app.core import events
from app.core.auth import (
    _get_user_from_token,
    create_access_token,
    create_refresh_token,
    get_user_from_refresh_token,
    hash_api_key,
    verify_password,
)
from app.core.identity import SCOPE_ACCESS
from app.modules.audit.models import AuditLog
from app.modules.enrollment.models import EnrollmentToken
from app.modules.notifications.models import NotificationSubscription
from app.modules.users.models import User
from app.modules.users.schemas import LoginRequest
from tests.token_claims import claims_for


def test_create_admin_creates_hashed_admin(db_session):
    assert create_admin(db_session, "kevin", "supersecret") == 0
    user = db_session.query(User).filter_by(username="kevin").one()
    assert user.is_admin is True
    assert user.hashed_password != "supersecret"
    assert verify_password("supersecret", user.hashed_password)


def test_create_admin_rejects_duplicate_username(db_session, admin_user):
    # admin_user already created "admin"
    assert create_admin(db_session, "admin", "password1") == 1


def test_create_admin_rejects_short_password(db_session):
    assert create_admin(db_session, "kev", "short") == 1
    assert db_session.query(User).filter_by(username="kev").first() is None


def test_a_cli_password_over_the_login_limit_could_not_log_in():
    # The reason for the CLI's upper bound: the login schema refuses such a password.
    with pytest.raises(ValidationError):
        LoginRequest(username="kev", password="x" * 129)
    LoginRequest(username="kev", password="x" * 128)


def test_create_admin_rejects_a_password_the_login_would_refuse(db_session, capsys):
    assert create_admin(db_session, "kev", "x" * 129) == 1
    assert db_session.query(User).filter_by(username="kev").first() is None
    assert "at most 128" in capsys.readouterr().err


def test_create_admin_accepts_a_password_at_the_login_limit(db_session):
    assert create_admin(db_session, "kev", "x" * 128) == 0


def test_mint_enroll_token_for_existing_user(db_session, admin_user):
    token = mint_enroll_token(db_session, "admin", ttl_minutes=60)
    assert token
    row = (
        db_session.query(EnrollmentToken)
        .filter(EnrollmentToken.hashed_token == hash_api_key(token))
        .one()
    )
    assert row.subject_id == "admin"
    assert row.scope == SCOPE_ACCESS
    assert row.browser is False
    assert row.is_valid()


def test_mint_enroll_token_unknown_user_returns_none(db_session):
    assert mint_enroll_token(db_session, "ghost", ttl_minutes=60) is None


class _FakeDB:
    def close(self):
        pass


def test_main_create_admin_reads_password_from_stdin(monkeypatch):
    # 3.31: --password-stdin reads the secret from stdin, so it never appears in the
    # process argv (/proc/<pid>/cmdline).
    captured = {}
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(cli, "create_admin", lambda db, u, p: captured.update(u=u, p=p) or 0)
    monkeypatch.setattr("sys.stdin", io.StringIO("stdin-secret\n"))
    assert cli.main(["create-admin", "--username", "kevin", "--password-stdin"]) == 0
    assert captured == {"u": "kevin", "p": "stdin-secret"}


def test_main_create_admin_still_accepts_password_arg(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(cli, "create_admin", lambda db, u, p: captured.update(u=u, p=p) or 0)
    assert cli.main(["create-admin", "--username", "kevin", "--password", "arg-secret"]) == 0
    assert captured == {"u": "kevin", "p": "arg-secret"}


@pytest.mark.parametrize("command", ["create-admin", "reset-admin"])
def test_main_refuses_password_together_with_password_stdin(restart, capsys, monkeypatch, command):
    # With both flags the restart would not fire and the --password value would stay in argv.
    monkeypatch.setattr(
        sys,
        "argv",
        ["app.cli", command, "--username", "kevin", "--password", "arg-secret", "--password-stdin"],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err
    assert restart.execv == []
    assert restart.dup2 == []


def test_main_create_admin_requires_a_password(monkeypatch):
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeDB())
    with pytest.raises(SystemExit):  # parser.error exits when neither is given
        cli.main(["create-admin", "--username", "kevin"])


def test_reset_admin_updates_password(db_session):
    assert create_admin(db_session, "kevin", "supersecret") == 0
    old_hash = db_session.query(User).filter_by(username="kevin").one().hashed_password
    assert reset_admin(db_session, "kevin", "brandneu99") == 0
    user = db_session.query(User).filter_by(username="kevin").one()
    assert user.hashed_password != old_hash
    assert verify_password("brandneu99", user.hashed_password)
    assert not verify_password("supersecret", user.hashed_password)


def test_reset_admin_signs_out_existing_sessions(db_session, admin_user):
    # Same token watermark as a password change over the API (users/router.py).
    access = create_access_token(claims_for("admin"))
    refresh = create_refresh_token(claims_for("admin"))
    assert _get_user_from_token(access, db_session) is not None
    assert get_user_from_refresh_token(refresh, db_session) is not None

    assert reset_admin(db_session, "admin", "brandneu99") == 0

    assert _get_user_from_token(access, db_session) is None
    assert get_user_from_refresh_token(refresh, db_session) is None
    # A JWT iat has whole seconds, and a token from the reset's own second counts
    # as issued before it (core/auth.py); a second later a new login holds.
    time.sleep(1)
    fresh = create_access_token(claims_for("admin"))
    assert _get_user_from_token(fresh, db_session) is not None


def test_reset_admin_refuses_unknown_user(db_session):
    assert reset_admin(db_session, "nobody", "brandneu99") == 1


def test_reset_admin_refuses_short_password(db_session):
    assert create_admin(db_session, "kevin", "supersecret") == 0
    assert reset_admin(db_session, "kevin", "kurz") == 1


def test_reset_admin_refuses_a_password_the_login_would_refuse(db_session, capsys):
    assert create_admin(db_session, "kevin", "supersecret") == 0
    assert reset_admin(db_session, "kevin", "x" * 129) == 1
    assert "at most 128" in capsys.readouterr().err
    user = db_session.query(User).filter_by(username="kevin").one()
    assert verify_password("supersecret", user.hashed_password)


def test_create_admin_gets_default_subscription(db_session):
    """T30: the install-time bootstrap admin must also get the baseline rule —
    it is the only user a fresh install has."""
    assert create_admin(db_session, "kevin", "supersecret") == 0
    user = db_session.query(User).filter_by(username="kevin").one()
    sub = (
        db_session.query(NotificationSubscription)
        .filter(NotificationSubscription.user_id == user.id)
        .one()
    )
    assert (sub.scope_type, sub.min_severity) == ("all", "warning")
    assert sub.enabled is True
    assert sub.channel_email is False
    assert sub.channel_telegram is False


def _audit_rows(db):
    return db.query(AuditLog).order_by(AuditLog.id).all()


def _assert_cli_actor(row):
    # R-0397: CLI actions are logged as actor system with the label cli.
    assert (row.actor_type, row.actor_id, row.actor_label, row.source_ip) == (
        "system",
        None,
        "cli",
        None,
    )


def test_create_admin_writes_one_audit_entry(db_session):
    assert create_admin(db_session, "kevin", "supersecret") == 0
    user = db_session.query(User).filter_by(username="kevin").one()
    [row] = _audit_rows(db_session)
    _assert_cli_actor(row)
    assert (row.action, row.object_type, row.object_id, row.object_label, row.status) == (
        "user.created",
        "user",
        str(user.id),
        "kevin",
        "success",
    )


def test_reset_admin_writes_one_audit_entry(db_session, admin_user):
    assert reset_admin(db_session, "admin", "brandneu99") == 0
    [row] = _audit_rows(db_session)
    _assert_cli_actor(row)
    assert (row.action, row.object_type, row.object_id, row.object_label, row.status) == (
        "user.password_reset",
        "user",
        str(admin_user.id),
        "admin",
        "success",
    )


def test_mint_enroll_token_writes_one_audit_entry(db_session, admin_user):
    assert mint_enroll_token(db_session, "admin", ttl_minutes=60)
    [row] = _audit_rows(db_session)
    _assert_cli_actor(row)
    assert (row.action, row.object_type, row.object_id, row.status) == (
        "enrollment.token.minted_for",
        "user",
        "admin",
        "success",
    )


@pytest.mark.parametrize(
    ("refused", "expected"),
    [
        (lambda db: create_admin(db, "kev", "short"), 1),
        (lambda db: create_admin(db, "admin", "password1"), 1),
        (lambda db: reset_admin(db, "nobody", "brandneu99"), 1),
        (lambda db: reset_admin(db, "admin", "kurz"), 1),
        (lambda db: mint_enroll_token(db, "ghost", ttl_minutes=60), None),
    ],
    ids=[
        "create-short-password",
        "create-existing-user",
        "reset-unknown-user",
        "reset-short-password",
        "mint-unknown-user",
    ],
)
def test_refused_cli_call_writes_no_audit_entry(db_session, admin_user, refused, expected):
    assert refused(db_session) == expected
    assert _audit_rows(db_session) == []


class _RecordingExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, /, *args, **kwargs):
        self.calls.append(args)
        future = Future()
        future.set_result(None)
        return future


@pytest.fixture()
def fired(monkeypatch):
    recorder = _RecordingExecutor()
    monkeypatch.setattr(events, "_executor", recorder)
    return recorder.calls


def test_create_admin_fires_user_created(db_session, fired):
    # Same event and payload as POST /api/users, so the security bell also
    # reports an admin created at the container shell.
    assert create_admin(db_session, "kevin", "supersecret") == 0
    user = db_session.query(User).filter_by(username="kevin").one()
    assert fired == [("user.created", {"id": user.id, "username": "kevin", "is_admin": True})]


@pytest.mark.parametrize(
    "refused",
    [
        lambda db: create_admin(db, "kev", "short"),
        lambda db: create_admin(db, "admin", "password1"),
    ],
    ids=["short-password", "existing-user"],
)
def test_refused_create_admin_fires_no_event(db_session, admin_user, fired, refused):
    assert refused(db_session) == 1
    assert fired == []


class _Execed(Exception):
    pass


def _create_admin_must_not_run(db, username, password):
    pytest.fail("create_admin ran in the process that has the password in its command line")


class _Restart:
    """main() as the real `python -m app.cli create-admin --password …` call, with
    os.dup2 and os.execv recorded instead of run."""

    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.dup2 = []
        self.execv = []

    def run(self, password, username_args=("--username", "kevin")):
        self._monkeypatch.setattr(
            sys, "argv", ["app.cli", "create-admin", *username_args, "--password", password]
        )
        # Patched only around the call: pytest's capture restores fd 1 and 2 with
        # os.dup2 after the test body, before the monkeypatch fixture undoes.
        with self._monkeypatch.context() as m:
            # Keeps the read end instead of putting it on the test's fd 0.
            m.setattr(cli.os, "dup2", lambda fd, fd2, inheritable=True: self.dup2.append((fd, fd2)))
            m.setattr(cli.os, "execv", self._execv)
            cli.main()

    def _execv(self, path, args):
        self.execv.append((path, args))
        raise _Execed


@pytest.fixture()
def restart(monkeypatch):
    monkeypatch.setattr(cli, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(cli, "create_admin", _create_admin_must_not_run)
    recorder = _Restart(monkeypatch)
    yield recorder
    for fd, _ in recorder.dup2:
        os.close(fd)


def _drain(fd):
    """Everything in the pipe, without blocking if its write end is still open."""
    os.set_blocking(fd, False)
    chunks = []
    try:
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
    except BlockingIOError:
        pass
    return b"".join(chunks)


def _pipe_size():
    read_end, write_end = os.pipe()
    try:
        return fcntl.fcntl(write_end, fcntl.F_GETPIPE_SZ)
    finally:
        os.close(read_end)
        os.close(write_end)


def test_main_create_admin_password_arg_restarts_with_the_password_on_stdin(restart):
    # create_admin fires user.created, whose hooks run in the CLI process: that
    # process must no longer carry the password in /proc/<pid>/cmdline.
    with pytest.raises(_Execed):
        restart.run("arg-secret")
    [(path, args)] = restart.execv
    assert path == sys.executable
    assert args == [
        sys.executable,
        "-m",
        "app.cli",
        "create-admin",
        "--username=kevin",
        "--password-stdin",
    ]
    assert not any("arg-secret" in arg for arg in args)
    [(read_end, target)] = restart.dup2
    assert target == 0
    assert _drain(read_end) == b"arg-secret\n"


def test_main_create_admin_restarted_process_gets_the_password(restart, monkeypatch):
    with pytest.raises(_Execed):
        restart.run("arg-secret")
    [(_, args)] = restart.execv
    [(read_end, _)] = restart.dup2
    captured = {}
    monkeypatch.setattr(cli, "create_admin", lambda db, u, p: captured.update(u=u, p=p) or 0)
    monkeypatch.setattr("sys.stdin", io.StringIO(_drain(read_end).decode()))
    assert cli.main(args[3:]) == 0
    assert captured == {"u": "kevin", "p": "arg-secret"}


def test_main_create_admin_restart_keeps_a_username_starting_with_a_dash(restart, monkeypatch):
    # The first call accepts `--username=-kev`; `--username -kev` in the restart
    # would make argparse take -kev for an option and exit 2.
    with pytest.raises(_Execed):
        restart.run("arg-secret", username_args=("--username=-kev",))
    [(_, args)] = restart.execv
    [(read_end, _)] = restart.dup2
    captured = {}
    monkeypatch.setattr(cli, "create_admin", lambda db, u, p: captured.update(u=u, p=p) or 0)
    monkeypatch.setattr("sys.stdin", io.StringIO(_drain(read_end).decode()))
    assert cli.main(args[3:]) == 0
    assert captured == {"u": "-kev", "p": "arg-secret"}


def test_main_create_admin_password_arg_with_a_newline_is_refused(restart, capsys):
    # --password-stdin reads one line, so the restarted process would cut it.
    with pytest.raises(SystemExit) as exc:
        restart.run("arg\nsecret")
    assert exc.value.code == 2
    assert "newline" in capsys.readouterr().err
    assert restart.execv == []
    assert restart.dup2 == []


def test_main_create_admin_password_arg_filling_the_pipe_is_passed_on(restart):
    password = "x" * (_pipe_size() - 1)  # with the newline: exactly one full pipe
    with pytest.raises(_Execed):
        restart.run(password)
    [(read_end, _)] = restart.dup2
    assert _drain(read_end) == password.encode() + b"\n"


def test_main_create_admin_password_arg_larger_than_the_pipe_is_refused(restart, capsys):
    # Written before the exec, so it has to fit into the pipe without a reader.
    with pytest.raises(SystemExit) as exc:
        restart.run("x" * _pipe_size())
    assert exc.value.code == 2
    assert "too long" in capsys.readouterr().err
    assert restart.execv == []
    assert restart.dup2 == []


# Runs in a child of its own: it closes fd 0, which the test process needs. The
# recorded execv reports what the exec would hand on and ends the child.
_CLOSED_STDIN_CHILD = """
import json, os, sys
import app.cli as cli

seen = {}
real_pipe = os.pipe

def pipe():
    fds = real_pipe()
    seen["read_end"] = fds[0]
    return fds

def execv(path, args):
    seen["inheritable"] = os.get_inheritable(0)
    seen["stdin"] = os.read(0, 100).decode()
    print(json.dumps(seen))
    raise SystemExit(0)

cli.os.pipe = pipe
cli.os.execv = execv
sys.argv = ["app.cli", "create-admin", "--username", "kevin", "--password", "arg-secret"]
os.close(0)
cli.main()
"""


def test_main_create_admin_restart_with_stdin_closed_keeps_the_pipe_on_fd_0():
    # `python -m app.cli … --password P <&-`: os.pipe() hands out fd 0 itself, and
    # dup2(0, 0) would leave it close-on-exec, so the new process had no stdin.
    result = subprocess.run(
        [sys.executable, "-c", _CLOSED_STDIN_CHILD],
        cwd=Path(cli.__file__).resolve().parents[1],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "read_end": 0,
        "inheritable": True,
        "stdin": "arg-secret\n",
    }
