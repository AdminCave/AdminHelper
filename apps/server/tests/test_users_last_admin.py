# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The last admin must not be demote-able (self-lockout guard, audit #11)."""

from app.core.auth import hash_password
from app.modules.users.models import User


def _login(client, username: str, password: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_cannot_demote_last_admin(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    r = test_client.put(
        f"/api/users/{admin_user.id}",
        json={"is_admin": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text
    db_session.refresh(admin_user)
    assert admin_user.is_admin is True


def test_can_demote_admin_when_another_exists(test_client, db_session, admin_user):
    db_session.add(
        User(username="admin2", hashed_password=hash_password("x2pass99"), is_admin=True)
    )
    db_session.commit()
    token = _login(test_client, "admin", "adminpass")
    r = test_client.put(
        f"/api/users/{admin_user.id}",
        json={"is_admin": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text


def test_a_name_taken_after_the_route_check_answers_409(
    test_client, db_session, admin_user, monkeypatch
):
    """R-1734: a user of the same name created between the route's check and its insert
    makes the insert fail on the unique name; the route answers 409, not 500."""
    from app.modules.users import service as users_service

    create_user = users_service.create_user

    def _competitor_first(db, **kwargs):
        db.execute(
            User.__table__.insert().values(
                username=kwargs["username"], hashed_password="x", is_admin=False
            )
        )
        return create_user(db, **kwargs)

    monkeypatch.setattr(users_service, "create_user", _competitor_first)
    token = _login(test_client, "admin", "adminpass")

    r = test_client.post(
        "/api/users",
        json={"username": "bob", "password": "bobpass99", "is_admin": False},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Benutzername bereits vergeben"
