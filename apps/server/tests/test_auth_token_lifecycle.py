# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auth lifecycle hardening (audit #3 refresh-reuse containment, #4 fail-closed)."""

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.auth import ALGORITHM, SECRET_KEY, token_claims
from app.core.rate_limit import RedisBackend
from app.core.time import utcnow_naive
from app.modules.users import auth_router


def _login(client, username="admin", password="adminpass"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def test_refresh_reuse_kills_whole_token_family(test_client, db_session, admin_user):
    r0 = _login(test_client)["refresh_token"]

    # Attacker refreshes first with the stolen R0 -> gets a fresh, valid pair.
    rot = test_client.post("/api/auth/refresh", json={"refresh_token": r0})
    assert rot.status_code == 200, rot.text
    a1, r1 = rot.json()["access_token"], rot.json()["refresh_token"]
    assert (
        test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {a1}"}).status_code
        == 200
    )

    # Victim later replays R0 -> reuse detected -> 401 AND the whole family dies.
    replay = test_client.post("/api/auth/refresh", json={"refresh_token": r0})
    assert replay.status_code == 401, replay.text

    # The attacker's rotated access token is now rejected...
    assert (
        test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {a1}"}).status_code
        == 401
    )
    # ...and their rotated refresh token can no longer mint new tokens.
    assert test_client.post("/api/auth/refresh", json={"refresh_token": r1}).status_code == 401


def test_concurrent_refresh_that_loses_the_blacklist_insert_is_reuse(
    test_client, monkeypatch, admin_user
):
    r0 = _login(test_client)["refresh_token"]
    rot = test_client.post("/api/auth/refresh", json={"refresh_token": r0})
    assert rot.status_code == 200, rot.text
    a1, r1 = rot.json()["access_token"], rot.json()["refresh_token"]

    # A second call with R0 ran its read checks (blacklist, token validity) before the
    # first call committed the blacklist row, so only its own insert finds the jti taken.
    with monkeypatch.context() as m:
        m.setattr(auth_router, "is_token_blacklisted", lambda *_: False)
        m.setattr(auth_router, "get_user_from_refresh_token", lambda *_: admin_user)
        late = test_client.post("/api/auth/refresh", json={"refresh_token": r0})
    assert late.status_code == 401, late.text

    # Counted as reuse: the pair the first call got is dead too.
    assert (
        test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {a1}"}).status_code
        == 401
    )
    assert test_client.post("/api/auth/refresh", json={"refresh_token": r1}).status_code == 401


def test_concurrent_refresh_that_sees_the_blacklist_row_after_its_precheck_is_reuse(
    test_client, monkeypatch, admin_user
):
    r0 = _login(test_client)["refresh_token"]
    rot = test_client.post("/api/auth/refresh", json={"refresh_token": r0})
    assert rot.status_code == 200, rot.text
    a1, r1 = rot.json()["access_token"], rot.json()["refresh_token"]

    # A second call with R0 ran only its blacklist pre-check before the first call
    # committed; its token-validity check already finds the row.
    real_is_token_blacklisted = auth_router.is_token_blacklisted
    calls = []

    def stale_precheck(token, db):
        calls.append(token)
        return False if len(calls) == 1 else real_is_token_blacklisted(token, db)

    with monkeypatch.context() as m:
        m.setattr(auth_router, "is_token_blacklisted", stale_precheck)
        late = test_client.post("/api/auth/refresh", json={"refresh_token": r0})
    assert late.status_code == 401, late.text

    # Counted as reuse: the pair the first call got is dead too.
    assert (
        test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {a1}"}).status_code
        == 401
    )
    assert test_client.post("/api/auth/refresh", json={"refresh_token": r1}).status_code == 401


def test_refresh_pair_predates_the_watermark_of_a_concurrent_reuse(
    test_client, db_session, monkeypatch, admin_user
):
    r0 = _login(test_client)["refresh_token"]
    real_blacklist_token = auth_router.blacklist_token

    def blacklist_then_concurrent_reuse(token, db):
        added = real_blacklist_token(token, db)
        # A concurrent call with the same token fails right after this commit and
        # sets the watermark (reuse); then time moves on to the next whole second.
        admin_user.tokens_valid_after = utcnow_naive()
        db_session.commit()
        time.sleep(1 - time.time() % 1)
        return added

    with monkeypatch.context() as m:
        m.setattr(auth_router, "blacklist_token", blacklist_then_concurrent_reuse)
        rot = test_client.post("/api/auth/refresh", json={"refresh_token": r0})
    assert rot.status_code == 200, rot.text
    a1, r1 = rot.json()["access_token"], rot.json()["refresh_token"]

    # The pair was issued before the blacklist commit, so the watermark covers it.
    assert (
        test_client.get("/api/auth/me", headers={"Authorization": f"Bearer {a1}"}).status_code
        == 401
    )
    assert test_client.post("/api/auth/refresh", json={"refresh_token": r1}).status_code == 401


@pytest.mark.parametrize("missing", ["jti", "exp"])
def test_refresh_token_without_jti_or_exp_is_reuse(test_client, db_session, admin_user, missing):
    # A signed, otherwise valid refresh token that cannot be blacklisted (no jti or no exp)
    # fails at the rotation step; that counts as reuse, so the account's watermark moves up.
    now = datetime.now(timezone.utc)
    claims = {
        **token_claims(admin_user),
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=1),
        "jti": "no-blacklist-row",
    }
    del claims[missing]
    forged = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)
    long_ago = datetime(2000, 1, 1)
    admin_user.tokens_valid_after = long_ago
    db_session.commit()

    resp = test_client.post("/api/auth/refresh", json={"refresh_token": forged})

    assert resp.status_code == 401, resp.text
    db_session.refresh(admin_user)
    assert admin_user.tokens_valid_after > long_ago


class _RedisDown:
    """A Redis client whose every op raises (simulates an outage)."""

    def get(self, key):
        raise RuntimeError("redis down")

    def pipeline(self):
        raise RuntimeError("redis down")

    def delete(self, key):
        raise RuntimeError("redis down")


def test_redis_backend_degrades_to_inmemory_not_fail_open():
    # Before the fix, get_count/increment returned 0 on any Redis error — silently
    # disabling the limit (fail-open). Now they degrade to a local counter so the
    # limit stays enforced during an outage.
    b = RedisBackend(_RedisDown())
    counts = [b.increment("brute:1.2.3.4", 60) for _ in range(5)]
    assert counts == [1, 2, 3, 4, 5], counts  # real counting, NOT stuck at 0
    assert b.get_count("brute:1.2.3.4") == 5
