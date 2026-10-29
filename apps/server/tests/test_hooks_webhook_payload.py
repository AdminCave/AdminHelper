# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The webhook trigger holds its JSON body to the rule of every request body: a NUL byte or a
lone surrogate in a string or a key is a 422 at its own place, and the script does not run.

The trigger takes any JSON and has no schema, so RequestModel (test_nul_body.py) never sees
its body. JSON spells the two only as escapes, \\u0000 and \\ud800; request.json() turns them
into the characters themselves, which survive the way to the worker and back. A script that
echoed such a payload made the answer a 500, since JSONResponse cannot write a lone surrogate,
and one that stored it failed at the database."""

import json

import pytest

from app.core.rate_limit import reset_backend_for_tests
from app.modules.hooks import router as hooks_router

_JSON = {"Content-Type": "application/json"}
_ECHO = "result['echo'] = payload"
_NUL = "Value error, must not contain a NUL byte"
_SURROGATE = "Value error, must not contain a lone surrogate (U+D800 to U+DFFF)"


def _admin_token(client) -> str:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _create_webhook(client, admin_token: str, script: str) -> str:
    r = client.post(
        "/api/hooks",
        json={"name": "wh", "hook_type": "webhook", "script": script},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


@pytest.fixture
def webhook(test_client, db_session, admin_user) -> str:
    reset_backend_for_tests()
    return _create_webhook(test_client, _admin_token(test_client), _ECHO)


@pytest.fixture
def script_runs(monkeypatch) -> list:
    """Every call of run_hook_script from the trigger; a refused body leaves it empty."""
    calls: list = []

    def record(**kwargs):
        calls.append(kwargs)
        return {"success": True, "result": {}, "logs": []}

    monkeypatch.setattr(hooks_router, "run_hook_script", record)
    return calls


def _detail(r) -> list:
    """The 422 as a client reads it: strict UTF-8 (a lone surrogate comes back escaped)."""
    assert (r.status_code, r.headers["content-type"]) == (422, "application/json"), r.text
    return json.loads(r.content.decode("utf-8"))["detail"]


# The JSON text of each body, with the escapes as a client sends them.
REFUSED = [
    pytest.param('{"a": "\\ud800"}', ["body", "a"], "\ud800", _SURROGATE, id="surrogate-value"),
    pytest.param(
        '{"items": ["ok", "x\\u0000y"]}', ["body", "items", 1], "x\x00y", _NUL, id="nul-in-list"
    ),
    pytest.param('{"k\\udc80": 1}', ["body", "k\udc80"], "k\udc80", _SURROGATE, id="surrogate-key"),
    pytest.param('"a\\udfffb"', ["body"], "a\udfffb", _SURROGATE, id="surrogate-top-level"),
]


@pytest.mark.parametrize(("body", "loc", "value", "msg"), REFUSED)
def test_a_nul_or_lone_surrogate_is_a_422_at_its_place(
    test_client, webhook, script_runs, body, loc, value, msg
):
    r = test_client.post(f"/api/hooks/trigger/{webhook}", content=body, headers=_JSON)
    assert [(d["type"], d["loc"], d["msg"], d["input"]) for d in _detail(r)] == [
        ("value_error", loc, msg, value)
    ]
    assert script_runs == []


def test_the_header_variant_refuses_it_too(test_client, webhook, script_runs):
    r = test_client.post(
        "/api/hooks/trigger",
        content='{"a": "\\ud800"}',
        headers={**_JSON, "X-Hook-Token": webhook},
    )
    assert [(d["loc"], d["msg"]) for d in _detail(r)] == [(["body", "a"], _SURROGATE)]
    assert script_runs == []


def test_token_and_enabled_are_checked_before_the_body(
    test_client, db_session, webhook, script_runs
):
    from app.modules.hooks.models import Hook

    bad = '{"a": "\\ud800"}'
    r = test_client.post("/api/hooks/trigger/definitiv-falsch", content=bad, headers=_JSON)
    assert r.status_code == 404, r.text

    hook = db_session.query(Hook).filter(Hook.hook_type == "webhook").first()
    hook.enabled = False
    db_session.commit()
    r = test_client.post(f"/api/hooks/trigger/{webhook}", content=bad, headers=_JSON)
    assert r.status_code == 403, r.text
    assert script_runs == []


def test_other_text_reaches_the_script_unchanged(test_client, webhook):
    # Umlauts, and a valid surrogate pair, which JSON reads as one character, are not refused.
    body = '{"gruss": "Grüße", "emoji": "\\ud83d\\ude00"}'.encode()
    r = test_client.post(f"/api/hooks/trigger/{webhook}", content=body, headers=_JSON)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["success"] is True, answer
    assert answer["result"]["echo"] == {"gruss": "Grüße", "emoji": "\U0001f600"}


def test_a_body_that_is_not_json_still_reaches_the_script_as_empty(test_client, webhook):
    r = test_client.post(f"/api/hooks/trigger/{webhook}", content=b"{not json", headers=_JSON)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["success"] is True, answer
    assert answer["result"]["echo"] == {}


# Python's json reads NaN, Infinity and -Infinity although JSON has no such numbers; the answer
# could not carry them back (JSONResponse writes with allow_nan=False).
NON_FINITE = [
    pytest.param('{"x": NaN}', ["body", "x"], id="nan"),
    pytest.param('{"a": [1, Infinity]}', ["body", "a", 1], id="infinity-in-list"),
    pytest.param("-Infinity", ["body"], id="minus-infinity-top-level"),
]


@pytest.mark.parametrize(("body", "loc"), NON_FINITE)
def test_a_non_finite_number_is_a_422_at_its_place(test_client, webhook, script_runs, body, loc):
    r = test_client.post(f"/api/hooks/trigger/{webhook}", content=body, headers=_JSON)
    assert [(d["type"], d["loc"], d["msg"]) for d in _detail(r)] == [
        ("value_error", loc, "Value error, must be a finite number")
    ]
    assert script_runs == []


def test_a_nan_body_the_script_would_echo_is_a_422_not_a_500(test_client, webhook):
    # The finding itself: the echo script returns the NaN, and the answer is a 422, not a 500.
    r = test_client.post(f"/api/hooks/trigger/{webhook}", content='{"x": NaN}', headers=_JSON)
    assert r.status_code == 422, r.text
