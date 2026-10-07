# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tz-naive DateTime columns hold naive UTC (audit F7, ``app/core/time.py``),
whatever the timezone of the database session.

An aware datetime bound to a ``TIMESTAMP WITHOUT TIME ZONE`` column is converted
with the session's ``TimeZone``, and the stack's postgres container runs with
``TZ=Europe/Berlin``. Each test reads the raw column back through the same
connection and compares it with naive UTC; the UTC session is the control case.
"""

from __future__ import annotations

import datetime

import jwt
import pytest
from sqlalchemy import text

from app.core.auth import blacklist_token, cleanup_expired_blacklist, hash_api_key
from app.core.config import ALGORITHM, SECRET_KEY
from app.modules.enrollment.models import EnrollmentToken
from app.modules.enrollment.service import DEFAULT_TTL, mint_enrollment_token
from app.modules.provisioning.models import ProvisionToken
from app.modules.servers.models import Server
from app.modules.users.models import TokenBlacklist

TOLERANCE = datetime.timedelta(seconds=30)
# The models are imported for their tables as well: pg_engine creates the schema
# from the models registered at session start, and run alone this file is the only
# one that registers ProvisionToken.


@pytest.fixture(params=["Europe/Berlin", "UTC"])
def tz_session(request, db_session):
    # SET inside the fixture's outer transaction: the rollback at teardown takes it
    # back, so the pooled connection keeps its default timezone.
    db_session.execute(text(f"SET TIME ZONE '{request.param}'"))
    return db_session


def _naive_utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _raw(db, sql: str, **params) -> datetime.datetime:
    return db.execute(text(sql), params).scalar_one()


def _assert_naive_utc(stored: datetime.datetime, expected: datetime.datetime) -> None:
    assert stored.tzinfo is None
    assert abs(stored - expected) <= TOLERANCE, (
        f"stored {stored.isoformat()}, expected naive UTC {expected.isoformat()} "
        f"(off by {stored - expected})"
    )


def _login(client) -> dict:
    res = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert res.status_code == 200, res.text
    return res.json()


def test_enrollment_token_row_stores_naive_utc(tz_session, admin_user):
    raw = mint_enrollment_token(tz_session, "admin", "access")
    stored = _raw(
        tz_session,
        f"SELECT expires_at FROM {EnrollmentToken.__tablename__} WHERE hashed_token = :h",
        h=hash_api_key(raw),
    )
    _assert_naive_utc(stored, _naive_utc_now() + DEFAULT_TTL)


def _provision_token(db, client) -> tuple[str, str]:
    """A server and a provision token minted through the API; (server id, raw token)."""
    srv = Server(id="srv-naive-utc", name="naive-utc", hostname="naive-utc.example.test")
    db.add(srv)
    db.commit()
    access = _login(client)["access_token"]
    res = client.post(
        f"/api/servers/{srv.id}/provision/token",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert res.status_code == 200, res.text
    return srv.id, res.json()["token"]


def test_provision_token_row_stores_naive_utc(tz_session, test_client, admin_user):
    _, raw = _provision_token(tz_session, test_client)
    stored = _raw(
        tz_session,
        f"SELECT expires_at FROM {ProvisionToken.__tablename__} WHERE hashed_token = :h",
        h=hash_api_key(raw),
    )
    _assert_naive_utc(stored, _naive_utc_now() + datetime.timedelta(hours=24))


def test_redeemed_provision_token_row_stores_naive_utc(tz_session, test_client, admin_user):
    server_id, raw = _provision_token(tz_session, test_client)
    res = test_client.post(
        f"/api/servers/{server_id}/provision/activate", headers={"X-Provision-Token": raw}
    )
    assert res.status_code == 200, res.text
    used = _raw(
        tz_session,
        f"SELECT used_at FROM {ProvisionToken.__tablename__} WHERE hashed_token = :h",
        h=hash_api_key(raw),
    )
    _assert_naive_utc(used, _naive_utc_now())


def test_token_blacklist_row_stores_naive_utc(tz_session, test_client, admin_user):
    access = _login(test_client)["access_token"]
    payload = jwt.decode(access, SECRET_KEY, algorithms=[ALGORITHM])
    assert blacklist_token(access, tz_session) is True
    stored = _raw(
        tz_session,
        f"SELECT expires_at FROM {TokenBlacklist.__tablename__} WHERE jti = :j",
        j=payload["jti"],
    )
    expected = datetime.datetime.fromtimestamp(payload["exp"], tz=datetime.timezone.utc)
    _assert_naive_utc(stored, expected.replace(tzinfo=None))


def test_blacklist_cleanup_compares_in_naive_utc(tz_session):
    # The reader side of the same convention: entries hold naive UTC, so the cutoff
    # must be naive UTC too — an aware one makes postgres read the column in the
    # session timezone.
    now = _naive_utc_now()
    hour = datetime.timedelta(hours=1)
    tz_session.add(TokenBlacklist(jti="naive-utc-expired", expires_at=now - 13 * hour))
    tz_session.add(TokenBlacklist(jti="naive-utc-current", expires_at=now + hour))
    tz_session.commit()

    cleanup_expired_blacklist(tz_session)

    left = _raw_jtis(tz_session)
    assert "naive-utc-expired" not in left
    assert "naive-utc-current" in left


def test_blacklist_cleanup_margin_covers_rows_from_before_f7(tz_session):
    # A row written before F7 holds the session's local time; west of UTC that is
    # up to 12 h behind. Due in one hour at UTC-8 it reads as 7 h ago, and it must
    # stay until it is really past. A row more than 12 h past goes.
    now = _naive_utc_now()
    hour = datetime.timedelta(hours=1)
    tz_session.add(TokenBlacklist(jti="local-time-row", expires_at=now + hour - 8 * hour))
    tz_session.add(TokenBlacklist(jti="past-margin", expires_at=now - 13 * hour))
    tz_session.commit()

    cleanup_expired_blacklist(tz_session)

    left = _raw_jtis(tz_session)
    assert "local-time-row" in left
    assert "past-margin" not in left


def _raw_jtis(db) -> set[str]:
    rows = db.execute(text(f"SELECT jti FROM {TokenBlacklist.__tablename__}")).scalars()
    return set(rows)
