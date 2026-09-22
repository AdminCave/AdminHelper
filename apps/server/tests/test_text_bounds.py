# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""NUL bytes are refused at the edge, not by the driver (T7).

Postgres stores no 0x00 in a text value. Until this change the byte travelled
all the way into psycopg, which raised DataError while binding the parameter —
uncaught, before any response existed, so the client saw HTTP 500. Reproduced
2026-09-22 on all seven sites below, and recorded before that in
tests/schemathesis_exclude.toml for POST /api/enrollment/token/for and
GET /api/audit.

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
