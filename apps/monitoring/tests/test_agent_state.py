# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1597: GET /agent/{server_id}/state, the internal route the server's provisioning
progress reads: the agent's last report and the host facts it carried."""

from datetime import datetime

from fastapi.testclient import TestClient

from app.models import MonitorAgentLiveness, MonitorHostFacts


def test_state_of_a_server_that_reported(client_db):
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorAgentLiveness(server_id="srv-1", last_report_at=datetime(2026, 11, 18, 9, 30))
        )
        db.add(
            MonitorHostFacts(
                server_id="srv-1", os="freebsd", platform="opnsense", platform_version="26.1"
            )
        )
        db.commit()

    r = client.get("/agent/srv-1/state")

    assert r.status_code == 200, r.text
    assert r.json() == {
        "lastReportAt": "2026-11-18T09:30:00Z",
        "hostFacts": {"os": "freebsd", "platform": "opnsense", "platformVersion": "26.1"},
    }


def test_unknown_server_answers_with_nulls_not_404(client_db):
    client, _ = client_db

    r = client.get("/agent/srv-unknown/state")

    assert r.status_code == 200, r.text
    assert r.json() == {"lastReportAt": None, "hostFacts": None}


def test_report_without_host_facts_keeps_them_null(client_db):
    # An agent before R-0421 reports without host facts: liveness alone.
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorAgentLiveness(server_id="srv-1", last_report_at=datetime(2026, 11, 18, 9, 30))
        )
        db.commit()

    body = client.get("/agent/srv-1/state").json()

    assert body["lastReportAt"] == "2026-11-18T09:30:00Z"
    assert body["hostFacts"] is None


def test_state_needs_the_internal_key(client_db):
    # The agent's own key does not open it: only the server reads another host's state.
    from app.core.auth import require_internal
    from app.main import app

    app.dependency_overrides.pop(require_internal)
    client = TestClient(app)

    assert client.get("/agent/srv-1/state").status_code == 401
    assert client.get("/agent/srv-1/state", headers={"X-Internal-Key": "wrong"}).status_code == 401
