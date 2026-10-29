# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-0685: the JSON routes declare a response model that maps today's answer key for key.

Pydantic drops a key the model does not declare without a word, so (a) the operation's 2xx
schema in the live OpenAPI names the model, and (b) the body over the real route equals what
the producer hands out, for a full row and a sparse one; (c) covers each conditional key."""

from datetime import datetime

import pytest
from fastapi.encoders import jsonable_encoder

from app.models import MonitorCheck, MonitorState


def _response_schema(path: str, method: str) -> dict:
    from app.main import app

    op = app.openapi()["paths"][path][method]
    status = next(code for code in op["responses"] if code.startswith("2"))
    return op["responses"][status]["content"]["application/json"]["schema"]


def _ref_name(schema: dict) -> str:
    if schema.get("type") == "array":
        schema = schema["items"]
    return schema["$ref"].rsplit("/", 1)[-1]


@pytest.mark.parametrize(
    ("path", "method", "model"),
    [
        ("/checks", "get", "MonitorCheckOut"),
        ("/checks", "post", "MonitorCheckOut"),
        ("/checks/{check_id}", "get", "MonitorCheckOut"),
        ("/checks/{check_id}", "put", "MonitorCheckOut"),
        ("/checks/{check_id}/toggle", "post", "MonitorCheckOut"),
        ("/checks/{check_id}/reset", "post", "MonitorCheckOut"),
        ("/checks/{check_id}/run", "post", "MonitorCheckOut"),
        ("/status", "get", "MonitorCheckOut"),
        ("/status/server/{server_id}", "get", "MonitorCheckOut"),
        ("/status/summary", "get", "StatusSummaryOut"),
        ("/checks/{check_id}/metrics", "get", "CheckMetricsOut"),
    ],
)
def test_routes_declare_their_response_model(path, method, model):
    assert _ref_name(_response_schema(path, method)) == model


def _seed_checks(factory):
    """chk-full: every nullable column set, a state row with JSON details; chk-sparse: every
    nullable column NULL and no state row, so the key state is absent (c)."""
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-full",
                server_id="srv-1",
                name="a-full",
                description="full row",
                check_type="ping",
                config='{"target": "192.0.2.10", "count": 3, "timeout": 1.5}',
                enabled=True,
                interval="1m",
                severity="warning",
                consecutive_fails=4,
                consecutive_oks=1,
                template_id="tpl-1",
                template_def_id="def-1",
                overridden_fields='["interval"]',
                created_at=datetime(2026, 10, 1, 12, 0, 0),
                updated_at=datetime(2026, 10, 2, 12, 0, 0),
            )
        )
        db.add(
            MonitorState(
                check_id="chk-full",
                status="warning",
                since=datetime(2026, 10, 3, 8, 0, 0),
                last_check=datetime(2026, 10, 3, 8, 5, 0),
                fail_count=2,
                message="slow",
                details='{"rtt_ms": 12.5, "lost": 1, "hops": ["a", "b"]}',
                notified_status="ok",
            )
        )
        db.add(
            MonitorCheck(
                id="chk-sparse",
                server_id=None,
                name="b-sparse",
                description=None,
                check_type="ping",
                config='{"target": "192.0.2.11"}',
                enabled=None,
                interval="5m",
                severity="critical",
                consecutive_fails=None,
                template_id=None,
                template_def_id=None,
            )
        )
        db.commit()


def _produced(factory, check_id: str) -> dict:
    with factory() as db:
        check = db.get(MonitorCheck, check_id)
        state = db.get(MonitorState, check_id)
        return jsonable_encoder(check.to_dict(state=state))


class TestCheckShape:
    def test_listings_equal_the_producer(self, client_db):
        client, factory = client_db
        _seed_checks(factory)
        want = [_produced(factory, "chk-full"), _produced(factory, "chk-sparse")]
        assert "state" in want[0] and "state" not in want[1]

        for path in ("/checks", "/status"):
            r = client.get(path)
            assert r.status_code == 200, r.text
            assert r.json() == want, path

        r = client.get("/status/server/srv-1")
        assert r.status_code == 200, r.text
        assert r.json() == want[:1]

    def test_single_check_equals_the_producer(self, client_db):
        client, factory = client_db
        _seed_checks(factory)
        for check_id in ("chk-full", "chk-sparse"):
            r = client.get(f"/checks/{check_id}")
            assert r.status_code == 200, r.text
            assert r.json() == _produced(factory, check_id), check_id

    def test_stored_numbers_stay_numbers(self, client_db):
        # Counter-check to test_stored_json_numbers: the model passes config and details
        # through as Any, no number becomes a string or a rounded value.
        client, factory = client_db
        _seed_checks(factory)
        body = client.get("/checks/chk-full").json()
        assert body["config"] == {"target": "192.0.2.10", "count": 3, "timeout": 1.5}
        assert body["state"]["details"] == {"rtt_ms": 12.5, "lost": 1, "hops": ["a", "b"]}

    def test_writes_answer_as_the_producer(self, client_db):
        client, factory = client_db
        r = client.post(
            "/checks",
            json={
                "name": "c",
                "check_type": "ping",
                "interval": "5m",
                "severity": "critical",
                "config": {"target": "192.0.2.12"},
            },
        )
        assert r.status_code == 201, r.text
        check_id = r.json()["id"]
        assert r.json() == _produced(factory, check_id)

        r = client.put(f"/checks/{check_id}", json={"description": "changed"})
        assert r.status_code == 200, r.text
        assert r.json() == _produced(factory, check_id)

        r = client.post(f"/checks/{check_id}/toggle")
        assert r.status_code == 200, r.text
        assert r.json() == _produced(factory, check_id)

    def test_reset_answers_as_the_producer(self, client_db):
        # Reset only takes a check a template rolled out.
        client, factory = client_db
        ping = {"def_id": "def-ping", "name": "Ping", "check_type": "ping"}
        ping["config"] = {"target": "{{hostname}}"}
        r = client.post("/templates", json={"name": "T", "check_definitions": [ping]})
        assert r.status_code == 201, r.text
        body = {"server_id": "srv-1", "hostname": "srv-1.example", "server_name": "srv-1"}
        assert client.post(f"/templates/{r.json()['id']}/assign", json=body).status_code == 200
        check_id = client.get("/checks", params={"server_id": "srv-1"}).json()[0]["id"]

        r = client.post(f"/checks/{check_id}/reset")
        assert r.status_code == 200, r.text
        assert r.json() == _produced(factory, check_id)


def test_status_summary_equals_the_producer(client_db):
    client, factory = client_db
    _seed_checks(factory)
    r = client.get("/status/summary")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "total": 1,
        "ok": 0,
        "warning": 1,
        "critical": 0,
        "unknown": 0,
        "pending": 0,
    }


def test_metrics_pass_the_series_through(client_db, monkeypatch):
    from app.core import victoria as victoria_mod

    client, factory = client_db
    _seed_checks(factory)
    series = [{"metric": {"__name__": "rtt"}, "values": [[1761800000, "12.5"]]}]
    monkeypatch.setattr(
        victoria_mod.victoria,
        "query_range",
        lambda **kw: {"status": "success", "data": {"result": series}},
    )
    r = client.get("/checks/chk-full/metrics", params={"period": "6h"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"checkId", "checkType", "period", "data", "statusHistory"}
    assert body["checkId"] == "chk-full" and body["period"] == "6h"
    assert body["statusHistory"] == series
    assert body["data"] and all(isinstance(s, dict) for s in body["data"])
