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


class TestHookTimestamps:
    def test_timestamps_are_rfc3339_utc(self, test_client, db_session, admin_user):
        # format: date-time promises an offset (R-0064): the API writes UTC with Z.
        from datetime import datetime

        from app.modules.hooks.models import Hook

        h = _login(test_client, "admin", "adminpass")
        r = test_client.post("/api/hooks", json={**WEBHOOK, "name": "wh-tz"}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["created_at"].endswith("Z"), r.text
        hook = db_session.get(Hook, r.json()["id"])
        hook.last_run = datetime(2026, 10, 5, 12, 0, 0)
        hook.next_run = datetime(2026, 10, 5, 13, 0, 0)
        db_session.commit()
        got = test_client.get(f"/api/hooks/{hook.id}", headers=h).json()
        assert got["last_run"] == "2026-10-05T12:00:00Z"
        assert got["next_run"] == "2026-10-05T13:00:00Z"
        listed = test_client.get("/api/hooks", headers=h).json()
        assert all(x["created_at"].endswith("Z") for x in listed)

    def test_manual_run_context_has_last_run_with_z(self, test_client, db_session, admin_user):
        # The script context carries last_run in UTC with Z (R-0064), like triggered_at.
        from datetime import datetime

        from app.modules.hooks.models import Hook

        h = _login(test_client, "admin", "adminpass")
        script = "result = {'last_run': last_run}"
        r = test_client.post(
            "/api/hooks", json={**WEBHOOK, "name": "wh-ctx", "script": script}, headers=h
        )
        assert r.status_code == 201, r.text
        db_session.get(Hook, r.json()["id"]).last_run = datetime(2026, 10, 5, 12, 0, 0)
        db_session.commit()
        run = test_client.post(f"/api/hooks/{r.json()['id']}/run", headers=h)
        assert run.status_code == 200, run.text
        assert run.json()["result"] == {"last_run": "2026-10-05T12:00:00Z"}, run.text

    def test_manual_run_context_has_triggered_at_with_z(self, test_client, db_session, admin_user):
        # One form per context (R-0064, Kevin 2026-10-06): triggered_at is UTC with Z too.
        h = _login(test_client, "admin", "adminpass")
        script = "result = {'triggered_at': triggered_at}"
        r = test_client.post(
            "/api/hooks", json={**WEBHOOK, "name": "wh-trig", "script": script}, headers=h
        )
        assert r.status_code == 201, r.text
        run = test_client.post(f"/api/hooks/{r.json()['id']}/run", headers=h)
        assert run.status_code == 200, run.text
        assert run.json()["result"]["triggered_at"].endswith("Z"), run.text

    def test_scheduled_run_context_has_last_run_with_z(self, db_session, monkeypatch):
        from datetime import datetime

        from sqlalchemy.orm import sessionmaker

        import app.core.database as database
        import app.modules.hooks.script_runner as script_runner
        from app.modules.hooks.models import Hook
        from app.modules.hooks.scheduler import _execute_scheduled_hook

        db_session.add(
            Hook(
                id="sched-tz",
                name="sched-tz",
                hook_type="schedule",
                script="pass",
                enabled=True,
                schedule_interval="1h",
                last_run=datetime(2026, 10, 5, 12, 0, 0),
            )
        )
        db_session.flush()
        seen: list[dict] = []
        monkeypatch.setattr(
            script_runner, "run_hook_script", lambda **kw: seen.append(kw["context"])
        )
        # _execute_scheduled_hook opens its own SessionLocal; bind it to the test connection.
        monkeypatch.setattr(
            database, "SessionLocal", sessionmaker(bind=db_session.connection(), autoflush=False)
        )

        _execute_scheduled_hook("sched-tz")

        assert [c["last_run"] for c in seen] == ["2026-10-05T12:00:00Z"]
        assert seen[0]["triggered_at"].endswith("Z"), seen


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

    @pytest.mark.parametrize(
        ("payload", "field", "msg"),
        [
            (
                {"name": "e", "hook_type": "event", "script": "x"},
                "event_triggers",
                "event_triggers erforderlich",
            ),
            (
                {"name": "e", "hook_type": "event", "script": "x", "event_triggers": ["bogus"]},
                "event_triggers",
                "Unbekanntes Event: 'bogus'",
            ),
            (
                {"name": "s", "hook_type": "schedule", "script": "x"},
                "schedule_interval",
                "schedule_interval erforderlich",
            ),
            (
                {"name": "s", "hook_type": "schedule", "script": "x", "schedule_interval": "nope"},
                "schedule_interval",
                "Ungültiges Intervall",
            ),
        ],
    )
    def test_invalid_create_answers_in_the_promised_format(
        self, test_client, db_session, admin_user, payload, field, msg
    ):
        # The OpenAPI promises HTTPValidationError for a 422 (R-0207): detail is a
        # list of {loc, msg, type}, not a string.
        h = _login(test_client, "admin", "adminpass")
        r = test_client.post("/api/hooks", json=payload, headers=h)
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert isinstance(detail, list) and len(detail) == 1, r.text
        assert detail[0]["loc"] == ["body", field], r.text
        assert detail[0]["type"] == "value_error", r.text
        assert detail[0]["msg"].startswith(msg), r.text

    @pytest.mark.parametrize(
        ("change", "field", "msg"),
        [
            ({"event_triggers": ["bogus"]}, "event_triggers", "Unbekanntes Event: 'bogus'"),
            ({"schedule_interval": "nope"}, "schedule_interval", "Ungültiges Intervall"),
        ],
    )
    def test_invalid_update_answers_in_the_promised_format(
        self, test_client, db_session, admin_user, change, field, msg
    ):
        h = _login(test_client, "admin", "adminpass")
        created = test_client.post("/api/hooks", json={**WEBHOOK, "name": "wh-upd"}, headers=h)
        assert created.status_code == 201, created.text
        r = test_client.put(f"/api/hooks/{created.json()['id']}", json=change, headers=h)
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert isinstance(detail, list) and len(detail) == 1, r.text
        assert detail[0]["loc"] == ["body", field], r.text
        assert detail[0]["msg"].startswith(msg), r.text

    @pytest.mark.parametrize("interval", ["a b c d e", "61 * * * *"])
    def test_a_cron_the_scheduler_cannot_read_is_422(
        self, test_client, db_session, admin_user, interval
    ):
        # R-0235: five fields are not yet a cron expression. The scheduler would reject
        # it and skip the hook on every reconcile, so the routes reject it up front.
        h = _login(test_client, "admin", "adminpass")
        payload = {
            "name": "s",
            "hook_type": "schedule",
            "script": "x",
            "schedule_interval": interval,
        }
        r = test_client.post("/api/hooks", json=payload, headers=h)
        assert r.status_code == 422, r.text
        assert r.json()["detail"][0]["loc"] == ["body", "schedule_interval"], r.text

        created = test_client.post("/api/hooks", json={**WEBHOOK, "name": "wh-cron"}, headers=h)
        assert created.status_code == 201, created.text
        r = test_client.put(
            f"/api/hooks/{created.json()['id']}", json={"schedule_interval": interval}, headers=h
        )
        assert r.status_code == 422, r.text
        assert r.json()["detail"][0]["loc"] == ["body", "schedule_interval"], r.text

    def test_a_valid_cron_is_accepted(self, test_client, db_session, admin_user):
        h = _login(test_client, "admin", "adminpass")
        payload = {
            "name": "s",
            "hook_type": "schedule",
            "script": "x",
            "schedule_interval": "*/5 * * * *",
        }
        r = test_client.post("/api/hooks", json=payload, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["schedule_interval"] == "*/5 * * * *"

    def test_valid_event_hook_created_201(self, test_client, db_session, admin_user):
        # The schedule happy path is test_a_valid_cron_is_accepted above: since the
        # scheduler process reconciles hooks, creating one needs no running APScheduler.
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


def test_webhook_trigger_via_header_token(test_client, db_session, admin_user):
    # 3.101: the token can be passed via the X-Hook-Token header instead of the URL path
    # (a path token leaks into access logs). Both variants work; a missing header 401s,
    # a wrong token 404s like the path variant.
    h = _login(test_client, "admin", "adminpass")
    r = test_client.post("/api/hooks", json={**WEBHOOK, "name": "wh-hdr-tok"}, headers=h)
    assert r.status_code == 201, r.text
    token = r.json()["token"]

    ok = test_client.post("/api/hooks/trigger", json={"x": 1}, headers={"X-Hook-Token": token})
    assert ok.status_code == 200, ok.text

    missing = test_client.post("/api/hooks/trigger", json={})
    assert missing.status_code == 401

    wrong = test_client.post("/api/hooks/trigger", json={}, headers={"X-Hook-Token": "nope"})
    assert wrong.status_code == 404


class TestHookWorkerRobustness:
    """4.69/4.70/4.71: the hook worker's timeout, response-size and result-return handling."""

    def test_result_rebinding_is_returned(self):
        # 4.71: a hook that rebinds `result = {...}` (instead of result[...] = ...) must have its
        # value returned, not silently lost — the worker reads namespace["result"], not the local.
        from app.modules.hooks.script_runner import run_hook_script

        out = run_hook_script("result = {'foo': 42}", "webhook", {})
        assert out["success"] is True
        assert out["result"] == {"foo": 42}

    def test_context_key_colliding_with_helper_is_rejected(self):
        # 4.71: an event context key that hits a helper/return name must be rejected, not silently
        # shadow the helper (or the result binding).
        from app.modules.hooks.script_runner import run_hook_script

        out = run_hook_script("pass", "webhook", {"result": "collision"})
        assert out["success"] is False
        assert "kollidiert" in (out.get("error", "") + " ".join(out.get("logs", [])))

    def test_oversized_http_body_aborts(self):
        # 4.70: _read_capped_body must raise once the streamed body exceeds _MAX_BODY, instead of
        # resp.text loading the whole (gigabyte) response into RAM first.
        from app.modules.hooks import script_worker

        class _FakeResp:
            encoding = "utf-8"

            def iter_bytes(self):
                for _ in range((script_worker._MAX_BODY // 1000) + 2):
                    yield b"x" * 1000

        with pytest.raises(ValueError, match="zu gross"):
            script_worker._read_capped_body(_FakeResp())

    def test_timeout_kills_grandchildren(self, tmp_path):
        # 4.69: a hook that spawns a grandchild must have the WHOLE process group killed on
        # timeout, not just the direct child — else the grandchild is orphaned and keeps running.
        import time

        from app.modules.hooks.script_runner import run_hook_script

        marker = tmp_path / "grandchild-marker"
        # Grandchild writes the marker after 4s, then the hook itself hangs. A 2s timeout must
        # kill the group before the grandchild's 4s write ever lands.
        script = (
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', "
            f"\"import time; time.sleep(4); open({str(marker)!r}, 'w').write('x')\"])\n"
            "time.sleep(30)\n"
        )
        out = run_hook_script(script, "webhook", {}, timeout=2)
        assert out["success"] is False
        time.sleep(5)  # past the grandchild's 4s write
        assert not marker.exists(), "grandchild survived the timeout kill (orphaned process)"
