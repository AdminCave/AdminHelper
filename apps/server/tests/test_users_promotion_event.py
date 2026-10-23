# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PUT /api/users/{id} fires user.promoted exactly when is_admin goes from false to
true, and an event hook can subscribe to it."""

from concurrent.futures import Future

import pytest

from app.core import events
from app.core.auth import hash_password
from app.modules.servers.models import Server
from app.modules.users.models import User

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
