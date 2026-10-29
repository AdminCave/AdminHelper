# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PUT /api/users/{id} fires user.promoted exactly when is_admin goes from false to
true, and an event hook can subscribe to it."""

import uuid
from concurrent.futures import Future, ThreadPoolExecutor

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import sessionmaker

from app.core import events
from app.core.auth import hash_password
from app.modules.notifications.models import NotificationSubscription
from app.modules.notifications.service import default_admin_subscription
from app.modules.servers.models import Server
from app.modules.users.models import User
from tests.test_identity_revocation import _a_session_waits_for

EVENT = "user.promoted"


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


def _promoted(calls):
    return [call for call in calls if call[0] == EVENT]


def _headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(db, name="promo-target", *, is_admin=False):
    user = User(username=name, hashed_password=hash_password("oldpass99"), is_admin=is_admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _put(client, user, body, expected=200):
    res = client.put(f"/api/users/{user.id}", headers=_headers(client), json=body)
    assert res.status_code == expected, res.text
    return res


def test_promotion_fires_one_event(test_client, db_session, admin_user, fired):
    user = _user(db_session)
    _put(test_client, user, {"is_admin": True})
    assert _promoted(fired) == [(EVENT, {"id": user.id, "username": "promo-target"})]


@pytest.mark.parametrize(
    "body, is_admin",
    [
        pytest.param({"is_admin": False}, True, id="demotion-with-two-admins"),
        pytest.param({"is_admin": True}, True, id="admin-stays-admin"),
        pytest.param({"password": "fresh-pw-7b2e"}, False, id="password-only"),
        pytest.param({"server_ids": ["srv-promo-a"]}, False, id="server-assignment-only"),
    ],
)
def test_other_changes_fire_no_event(test_client, db_session, admin_user, fired, body, is_admin):
    db_session.add(Server(id="srv-promo-a", name="A", hostname="a.example"))
    db_session.commit()
    user = _user(db_session, is_admin=is_admin)
    _put(test_client, user, body)
    assert _promoted(fired) == []
    # The same route on the same user fires once it promotes.
    if is_admin:
        _put(test_client, user, {"is_admin": False})
    _put(test_client, user, {"is_admin": True})
    assert _promoted(fired) == [(EVENT, {"id": user.id, "username": "promo-target"})]


def test_refused_demotion_of_last_admin_fires_no_event(test_client, db_session, admin_user, fired):
    _put(test_client, admin_user, {"is_admin": False}, expected=400)
    assert fired == []


def test_event_hook_can_subscribe(test_client, db_session, admin_user):
    res = test_client.post(
        "/api/hooks",
        headers=_headers(test_client),
        json={
            "name": "on-promotion",
            "hook_type": "event",
            "script": "-- noop",
            "event_triggers": [EVENT],
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["event_triggers"] == [EVENT]


@pytest.fixture()
def race_target(pg_engine):
    # Committed through its own connection, so a second session can lock the row; listed
    # before test_client/db_session, so this teardown runs after their rollback, which
    # releases the row lock the PUT took.
    new_session = sessionmaker(bind=pg_engine)
    with new_session() as setup:
        user = User(
            username=f"promo-race-{uuid.uuid4().hex[:8]}",
            hashed_password=hash_password("oldpass99"),
            is_admin=False,
        )
        setup.add(user)
        setup.commit()
        user_id = user.id
    yield user_id
    with pg_engine.begin() as conn:
        conn.execute(
            delete(NotificationSubscription).where(NotificationSubscription.user_id == user_id)
        )
        conn.execute(delete(User).where(User.id == user_id))


def test_a_concurrent_promotion_adds_no_second_rule_and_no_second_event(
    race_target, pg_engine, test_client, db_session, admin_user, fired
):
    headers = _headers(test_client)
    other = sessionmaker(bind=pg_engine)()
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        target = other.query(User).filter(User.id == race_target).with_for_update().one()
        other_pid = other.execute(text("SELECT pg_backend_pid()")).scalar()
        putting = ex.submit(
            test_client.put,
            f"/api/users/{race_target}",
            headers=headers,
            json={"is_admin": True},
        )
        assert _a_session_waits_for(pg_engine, other_pid), "the PUT must wait for the row"
        target.is_admin = True
        other.add(default_admin_subscription(race_target))
        other.commit()
        res = putting.result(10)
        assert res.status_code == 200, res.text
    finally:
        other.close()
        ex.shutdown(wait=True)
    rules = (
        db_session.query(NotificationSubscription)
        .filter(NotificationSubscription.user_id == race_target)
        .count()
    )
    assert rules == 1, f"{rules} rules"
    assert _promoted(fired) == []
