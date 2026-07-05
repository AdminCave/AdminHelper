# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hooks module: admin-only authz, type-specific create validation, and — the
part that previously had no test — the event dispatch actually selecting the
right hooks. Hooks run user-supplied scripts, so "does server.created fire the
matching hook (and only that one)?" is worth pinning down."""

import json

import pytest

WEBHOOK = {"name": "wh", "hook_type": "webhook", "script": "-- noop"}


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestHooksAuthz:
    def test_nonadmin_cannot_list(self, test_client, db_session, normal_user):
        h = _login(test_client, "viewer", "viewerpass")
        assert test_client.get("/api/hooks", headers=h).status_code == 403

    def test_nonadmin_cannot_create(self, test_client, db_session, normal_user):
        h = _login(test_client, "viewer", "viewerpass")
        assert test_client.post("/api/hooks", json=WEBHOOK, headers=h).status_code == 403

    def test_unauthenticated_cannot_list(self, test_client, db_session):
        assert test_client.get("/api/hooks").status_code == 401


class TestHookCreateValidation:
    def test_webhook_created_with_token(self, test_client, db_session, admin_user):
        h = _login(test_client, "admin", "adminpass")
        r = test_client.post("/api/hooks", json=WEBHOOK, headers=h)
        assert r.status_code == 201, r.text
        assert r.json().get("token")  # the one-time webhook token is returned

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "e", "hook_type": "event", "script": "x"},  # event_triggers missing
            {"name": "e", "hook_type": "event", "script": "x", "event_triggers": ["bogus.event"]},
            {"name": "s", "hook_type": "schedule", "script": "x"},  # interval missing
            {"name": "s", "hook_type": "schedule", "script": "x", "schedule_interval": "nope"},
            {"name": "u", "hook_type": "frobnicate", "script": "x"},  # unknown type
        ],
    )
    def test_invalid_create_rejected_422(self, test_client, db_session, admin_user, payload):
        h = _login(test_client, "admin", "adminpass")
        assert test_client.post("/api/hooks", json=payload, headers=h).status_code == 422

    def test_valid_event_hook_created_201(self, test_client, db_session, admin_user):
        # A valid schedule hook additionally needs the running APScheduler
        # (started in the app lifespan, not in tests), so its happy path is an
        # integration concern; the schedule *validation* is covered above (422).
        h = _login(test_client, "admin", "adminpass")
        payload = {
            "name": "e",
            "hook_type": "event",
            "script": "x",
            "event_triggers": ["server.created"],
        }
        assert test_client.post("/api/hooks", json=payload, headers=h).status_code == 201


class TestEventDispatch:
    def test_runs_only_matching_enabled_event_hooks(self, db_session, monkeypatch):
        from sqlalchemy.orm import sessionmaker

        import app.core.database as database
        import app.modules.hooks.script_runner as script_runner
        from app.core.events import _run_event
        from app.modules.hooks.models import Hook

        def hook(name, triggers, enabled=True):
            return Hook(
                id=name,
                name=name,
                hook_type="event",
                script=f"-- {name}",
                enabled=enabled,
                event_triggers=json.dumps(triggers),
            )

        db_session.add_all(
            [
                hook("match-enabled", ["server.created"]),
                hook("match-disabled", ["server.created"], enabled=False),
                hook("other-event", ["user.created"]),
            ]
        )
        db_session.flush()

        ran: list[str] = []
        monkeypatch.setattr(script_runner, "run_hook_script", lambda **kw: ran.append(kw["script"]))
        # _run_event opens its own SessionLocal; bind a fresh one to the test
        # connection so it sees the (uncommitted) hooks created above.
        monkeypatch.setattr(
            database, "SessionLocal", sessionmaker(bind=db_session.connection(), autoflush=False)
        )

        _run_event("server.created", {"id": "s1"})

        assert ran == ["-- match-enabled"]


def test_valid_intervals_matches_scheduler_map():
    """2.50: the 422 interval error lists VALID_INTERVALS while the validator
    accepts anything in INTERVAL_MAP — they must be the same set, else the message
    hides a valid interval ("1m" had drifted out of VALID_INTERVALS)."""
    from app.modules.hooks.scheduler import INTERVAL_MAP
    from app.modules.hooks.schemas import VALID_INTERVALS

    assert "1m" in VALID_INTERVALS
    assert set(VALID_INTERVALS) == set(INTERVAL_MAP)


def test_webhook_context_headers_are_safe_listed(test_client, db_session, admin_user):
    # 3.36: the privileged webhook script context must not receive client-controlled
    # credentials/spoofable headers (Authorization/Cookie/X-Forwarded-*) — only a
    # safe allow-list. Otherwise a naive hook could forward them to a payload-chosen URL.
    h = _login(test_client, "admin", "adminpass")
    hook = {
        "name": "wh-hdr",
        "hook_type": "webhook",
        "script": "import json\nlog(json.dumps(headers))",
    }
    r = test_client.post("/api/hooks", json=hook, headers=h)
    assert r.status_code == 201, r.text
    token = r.json()["token"]

    trig = test_client.post(
        f"/api/hooks/trigger/{token}",
        json={"x": 1},
        headers={
            "Authorization": "Bearer super-secret",
            "Cookie": "session=leak-me",
            "X-Forwarded-For": "10.9.9.9",
            "Content-Type": "application/json",
            "X-Hook-Source": "pytest",
        },
    )
    assert trig.status_code == 200, trig.text
    logged = " ".join(trig.json()["logs"]).lower()
    # dangerous / spoofable headers are stripped
    assert "super-secret" not in logged
    assert "leak-me" not in logged
    assert "authorization" not in logged
    assert "cookie" not in logged
    assert "x-forwarded-for" not in logged
    # the safe custom header still reaches the script
    assert "x-hook-source" in logged
