# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The running scheduler changes only after the DB commit succeeded (R-0695).

A job is built from the DB only when the service starts. Removing it before a commit that
then fails leaves a check in the DB that no longer runs until the next restart; the
template sync already orders it this way (template_sync.apply_scheduler_actions). The
order is invisible to a test that only looks at the end state, so an after_commit
listener and a recorder for remove_check write one event list.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.models import MonitorCheck, MonitorTemplate


@pytest.fixture()
def recorded(client_db, monkeypatch):
    """(client, factory, events): events gets "commit" per successful commit of the
    request sessions and "remove:<id>" per remove_check of either router."""
    client, factory = client_db
    events: list[str] = []
    event.listen(factory, "after_commit", lambda session: events.append("commit"))

    def remove(check_id):
        events.append(f"remove:{check_id}")

    monkeypatch.setattr("app.routers.checks.remove_check", remove)
    monkeypatch.setattr("app.routers.templates.remove_check", remove)
    monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
    return client, factory, events


def _seed(factory, *, template_id=None, check_ids=("chk-1",)):
    with factory() as db:
        if template_id:
            db.add(
                MonitorTemplate(
                    id=template_id, name="T", check_definitions="[]", alert_definitions="[]"
                )
            )
        for check_id in check_ids:
            db.add(
                MonitorCheck(
                    id=check_id,
                    server_id="srv-1",
                    name=check_id,
                    check_type="ping",
                    config="{}",
                    enabled=True,
                    template_id=template_id,
                )
            )
        db.commit()


def _fail_commits(factory):
    def boom(session):
        raise RuntimeError("commit refused")

    event.listen(factory, "before_commit", boom)


def _server_errors_answered():
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def test_deleting_a_check_unschedules_it_after_the_commit(recorded):
    client, factory, events = recorded
    _seed(factory)
    events.clear()

    assert client.delete("/checks/chk-1").status_code == 204

    assert events == ["commit", "remove:chk-1"]


def test_a_failed_check_delete_keeps_the_job(recorded):
    _client, factory, events = recorded
    _seed(factory)
    events.clear()
    _fail_commits(factory)

    assert _server_errors_answered().delete("/checks/chk-1").status_code == 500

    assert events == []
    with factory() as db:
        assert db.get(MonitorCheck, "chk-1") is not None


def test_deleting_a_template_unschedules_its_checks_after_the_commit(recorded):
    client, factory, events = recorded
    _seed(factory, template_id="tpl-1", check_ids=("chk-a", "chk-b"))
    events.clear()

    assert client.delete("/templates/tpl-1").status_code == 204

    assert events[0] == "commit"
    assert sorted(events[1:]) == ["remove:chk-a", "remove:chk-b"]


def test_a_failed_template_delete_keeps_the_jobs(recorded):
    _client, factory, events = recorded
    _seed(factory, template_id="tpl-1", check_ids=("chk-a", "chk-b"))
    events.clear()
    _fail_commits(factory)

    assert _server_errors_answered().delete("/templates/tpl-1").status_code == 500

    assert events == []
    with factory() as db:
        assert db.get(MonitorTemplate, "tpl-1") is not None
        assert db.query(MonitorCheck).filter(MonitorCheck.template_id == "tpl-1").count() == 2


def test_toggling_a_check_off_unschedules_it_after_the_commit(recorded):
    client, factory, events = recorded
    _seed(factory)
    events.clear()

    assert client.post("/checks/chk-1/toggle").status_code == 200

    assert events == ["commit", "remove:chk-1"]
