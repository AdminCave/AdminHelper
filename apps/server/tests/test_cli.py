# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Management CLI (`app.cli`): the install-time bootstrap of the first admin +
its enrollment token, so a fresh deployment can come up with mTLS enforced."""

from __future__ import annotations

import io

import pytest

import app.cli as cli
from app.cli import create_admin, mint_enroll_token, reset_admin
from app.core.auth import hash_api_key, verify_password
from app.core.identity import SCOPE_ACCESS
from app.modules.enrollment.models import EnrollmentToken
from app.modules.notifications.models import NotificationSubscription
from app.modules.users.models import User


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


def test_reset_admin_refuses_unknown_user(db_session):
    assert reset_admin(db_session, "nobody", "brandneu99") == 1


def test_reset_admin_refuses_short_password(db_session):
    assert create_admin(db_session, "kevin", "supersecret") == 0
    assert reset_admin(db_session, "kevin", "kurz") == 1


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
