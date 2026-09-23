# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""NUL bytes are refused at the edge, not by the driver (T7).

Postgres stores no 0x00 in a text value. Until this change the byte travelled
all the way into psycopg, which raised DataError while binding the parameter —
uncaught, before any response existed, so the client saw HTTP 500. Reproduced
2026-09-22 on all seven sites below, and recorded before that in
tests/schemathesis_exclude.toml for POST /api/enrollment/token/for and
GET /api/audit. POST /api/hooks came out of the fuzz run of the same day, once
those exclusions were off and not_a_server_error could see the route again.

The bound is deliberately only the NUL byte: every other control character is
storable, and the TOML-injection guards in frp/schemas.py are a separate
concern."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.bounds import SafeText

NUL = chr(0)
AUDIT_FILTERS = ("action", "actor_type", "object_type", "object_id", "status", "q")


def _login(test_client) -> dict:
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_safetext_passes_everything_but_nul():
    adapter = TypeAdapter(SafeText)
    # Not a general control-character guard: a tab, a newline and a DEL all pass.
    for ok in ("", "plain", "a\tb", "a\nb", "a\x7fb", "ä€"):
        assert adapter.validate_python(ok) == ok
    for bad in (NUL, "a" + NUL, NUL + "a", "a" + NUL + "b"):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


@pytest.mark.parametrize("field", AUDIT_FILTERS)
def test_audit_filters_reject_a_nul_byte(field, test_client, db_session, admin_user):
    headers = _login(test_client)

    ok = test_client.get("/api/audit", params={field: "plain"}, headers=headers)
    assert ok.status_code == 200, f"{field}: {ok.status_code} {ok.text}"

    nul = test_client.get("/api/audit", params={field: "a" + NUL + "b"}, headers=headers)
    assert nul.status_code == 422, f"{field}: {nul.status_code} {nul.text}"


def test_enrollment_token_for_rejects_a_nul_username(test_client, db_session, admin_user):
    headers = _login(test_client)

    # A username that does not exist answers 404 — the value reached the lookup.
    ok = test_client.post("/api/enrollment/token/for", json={"username": "ghost"}, headers=headers)
    assert ok.status_code == 404, ok.text

    nul = test_client.post(
        "/api/enrollment/token/for", json={"username": "a" + NUL + "b"}, headers=headers
    )
    assert nul.status_code == 422, nul.text
    assert nul.json()["detail"][0]["loc"][-1] == "username"


def test_hook_script_rejects_a_nul_byte(test_client, db_session, admin_user):
    """Found by the fuzzer, not by reading: with the old exclusions gone,
    POST /api/hooks with a NUL in `script` died in the INSERT (T10)."""
    headers = _login(test_client)

    ok = test_client.post(
        "/api/hooks",
        json={"name": "h1", "hook_type": "webhook", "script": "result = {}"},
        headers=headers,
    )
    assert ok.status_code == 201, ok.text

    nul = test_client.post(
        "/api/hooks",
        json={"name": "h2", "hook_type": "webhook", "script": NUL},
        headers=headers,
    )
    assert nul.status_code == 422, nul.text
    assert nul.json()["detail"][0]["loc"][-1] == "script"


def test_user_server_ids_reject_a_nul_byte(test_client, db_session, admin_user):
    """server_ids carries no numeric bound — servers.id is a String column — but a
    NUL in one of them reached Server.id.in_() and died in the driver (found by
    the fuzzer on POST /api/users, 2026-09-22)."""
    headers = _login(test_client)
    body = {"username": "newuser", "password": "supersecret1", "server_ids": ["srv-a"]}

    ok = test_client.post("/api/users", json=body, headers=headers)
    assert ok.status_code == 201, ok.text

    nul = test_client.post(
        "/api/users",
        json={**body, "username": "other", "server_ids": ["srv-a", "b" + NUL]},
        headers=headers,
    )
    assert nul.status_code == 422, nul.text
    assert nul.json()["detail"][0]["loc"][-2] == "server_ids"


def test_internal_event_fields_reject_a_nul_byte(test_client, db_session, admin_user, monkeypatch):
    """Found by the fuzzer on `source_id` (2026-09-22): every text field of an
    incoming event is written verbatim into a Notification row, and source_id is
    compared against Server.id on the way."""
    monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
    headers = {"X-Internal-Key": "secret"}
    payload = {
        "event_type": "monitoring.check.transition",
        "severity": "critical",
        "category": "monitoring",
        "title": "CPU critical on web01",
        "source_type": "server",
        "source_id": "srv-1",
    }

    ok = test_client.post("/api/internal/events", json=payload, headers=headers)
    assert ok.status_code == 202, ok.text

    for field in (
        "event_type",
        "category",
        "title",
        "body",
        "source_type",
        "source_id",
        "new_status",
    ):
        r = test_client.post(
            "/api/internal/events", json={**payload, field: "a" + NUL}, headers=headers
        )
        assert r.status_code == 422, f"{field}: {r.status_code} {r.text}"
        assert r.json()["detail"][0]["loc"][-1] == field


def test_api_key_name_rejects_a_nul_byte(test_client, db_session, admin_user):
    """Found by the fuzzer while verifying an unrelated task (2026-09-23):
    ApiKeyCreate.name went into Column(String) unguarded, so a NUL died in the
    INSERT. The route was never under an exclusion — it only fails when
    Hypothesis happens to draw a NUL for the name."""
    headers = _login(test_client)

    ok = test_client.post(
        "/api/api-keys", json={"name": "k1", "permission": "read"}, headers=headers
    )
    assert ok.status_code == 201, ok.text

    nul = test_client.post(
        "/api/api-keys", json={"name": NUL, "permission": "read"}, headers=headers
    )
    assert nul.status_code == 422, nul.text
    assert nul.json()["detail"][0]["loc"][-1] == "name"
