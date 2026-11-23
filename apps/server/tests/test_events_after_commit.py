# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""queue_event fires once the session's transaction commits, and never if it does not (R-0689).

The pool is bounded (MAX_PENDING) and shutdown_events waits a bounded time for it.
"""

import logging
import threading
from concurrent.futures import Future

import pytest

from app.core import events
from app.core.auth import hash_password
from app.modules.users import router as users_router
from app.modules.users.models import User
from tests.test_users_promotion_event import _headers

EVENT = "test.after-commit"


class _RecordingExecutor:
    def __init__(self, *, finished=True, error=None):
        self.calls = []
        self.futures = []
        self._finished = finished
        self._error = error

    def submit(self, fn, /, *args, **kwargs):
        if self._error is not None:
            raise self._error
        self.calls.append(args)
        future = Future()
        if self._finished:
            future.set_result(None)
        self.futures.append(future)
        return future


@pytest.fixture()
def executor(monkeypatch):
    recorder = _RecordingExecutor()
    monkeypatch.setattr(events, "_executor", recorder)
    return recorder


@pytest.fixture()
def stalled(monkeypatch):
    # Futures that never finish, as a hanging hook leaves them; cancelled at the end so
    # nothing stays counted against MAX_PENDING for the next test.
    recorder = _RecordingExecutor(finished=False)
    monkeypatch.setattr(events, "_executor", recorder)
    yield recorder
    for future in recorder.futures:
        future.cancel()
    assert events._pending == set()


def test_commit_fires_the_queued_event_once(db_session, executor):
    events.queue_event(db_session, EVENT, {"id": 7})
    assert executor.calls == []

    db_session.commit()
    db_session.commit()

    assert executor.calls == [(EVENT, {"id": 7})]


def test_rollback_drops_the_queued_event(db_session, executor):
    events.queue_event(db_session, EVENT, {"id": 7})
    db_session.rollback()
    db_session.commit()

    assert executor.calls == []


def test_close_drops_the_queued_event(db_session, executor):
    events.queue_event(db_session, EVENT, {"id": 7})
    db_session.close()
    db_session.commit()

    assert executor.calls == []


def test_a_savepoint_commit_waits_for_the_outer_commit(db_session, executor):
    with db_session.begin_nested():
        events.queue_event(db_session, EVENT, {"id": 7})
    assert executor.calls == []

    db_session.commit()
    assert executor.calls == [(EVENT, {"id": 7})]


def test_a_failed_dispatch_leaves_the_commit_standing(db_session, monkeypatch, caplog):
    monkeypatch.setattr(events, "_executor", _RecordingExecutor(error=RuntimeError("pool down")))
    events.queue_event(db_session, EVENT, {"id": 7})

    with caplog.at_level(logging.ERROR, logger=events.__name__):
        db_session.commit()

    assert [r.getMessage() for r in caplog.records] == [
        f"Event dispatch after commit failed (event={EVENT})"
    ]
    assert db_session.info.get(events._QUEUED_KEY) is None


def test_past_max_pending_an_event_is_dropped_with_a_warning(stalled, caplog):
    with caplog.at_level(logging.WARNING, logger=events.__name__):
        for _ in range(events.MAX_PENDING + 2):
            events.fire_event(EVENT, None)

    assert len(stalled.calls) == events.MAX_PENDING
    assert [r.getMessage() for r in caplog.records] == [
        f"Event queue full ({events.MAX_PENDING}), event {EVENT} dropped"
    ] * 2

    stalled.futures[0].set_result(None)
    events.fire_event(EVENT, None)
    assert len(stalled.calls) == events.MAX_PENDING + 1


def test_shutdown_waits_for_a_running_event(stalled, caplog):
    events.fire_event(EVENT, "finishes")
    (finishing,) = stalled.futures
    threading.Timer(0.05, finishing.set_result, args=(None,)).start()

    # The generous timeout is only a ceiling: shutdown_events returns once the event is done.
    with caplog.at_level(logging.WARNING, logger=events.__name__):
        events.shutdown_events(timeout=30)

    assert finishing.result() is None
    assert caplog.records == []


def test_shutdown_drops_what_has_not_started_after_the_timeout(stalled, caplog):
    events.fire_event(EVENT, "queued")
    events.fire_event(EVENT, "hangs")
    queued, hanging = stalled.futures
    hanging.set_running_or_notify_cancel()

    # This test is about the deadline itself: neither future can finish, so the short
    # timeout always runs out.
    with caplog.at_level(logging.WARNING, logger=events.__name__):
        events.shutdown_events(timeout=0.1)

    assert queued.cancelled()
    assert not hanging.done()
    assert [r.getMessage() for r in caplog.records] == [
        "Shutdown: 2 event(s) unfinished after 0.1 s, 1 dropped"
    ]
    hanging.set_result(None)


def test_shutdown_with_nothing_pending_returns_at_once(executor, caplog):
    events.fire_event(EVENT, None)

    with caplog.at_level(logging.WARNING, logger=events.__name__):
        events.shutdown_events(timeout=30)

    assert caplog.records == []


def _deleted(calls):
    return [call for call in calls if call[0] == "user.deleted"]


def _target(db):
    user = User(username="delete-target", hashed_password=hash_password("oldpass99"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_deleting_a_user_fires_user_deleted_once(test_client, db_session, admin_user, executor):
    user = _target(db_session)
    res = test_client.delete(f"/api/users/{user.id}", headers=_headers(test_client))
    assert res.status_code == 204, res.text
    assert _deleted(executor.calls) == [
        ("user.deleted", {"id": user.id, "username": "delete-target"})
    ]


@pytest.mark.parametrize("failing", ["revoke_identity", "commit"])
def test_a_failed_user_delete_fires_no_user_deleted(
    test_client, db_session, admin_user, executor, monkeypatch, failing
):
    user = _target(db_session)
    headers = _headers(test_client)

    def broken(*args, **kwargs):
        raise RuntimeError(f"{failing} failed")

    # Only the failure is undone afterwards: the recorder must stay in place, so an event
    # left queued on the session would show at the next commit.
    with monkeypatch.context() as mp:
        if failing == "commit":
            mp.setattr(db_session, "commit", broken)
        else:
            mp.setattr(users_router, failing, broken)
        with pytest.raises(RuntimeError):
            test_client.delete(f"/api/users/{user.id}", headers=headers)
    assert events._executor is executor
    # The request's session ends without a commit, as get_db's close would end it.
    db_session.rollback()
    db_session.commit()

    assert _deleted(executor.calls) == []
    assert db_session.get(User, user.id) is not None


# One request per call site: success queues exactly one event, which fires with the
# commit. An event queued after the commit sits on the session instead: the test session
# is not closed after a request, and audit.record commits on it, so it is silenced here,
# or its commit would fire a late event as if it were on time.


@pytest.fixture()
def quiet_audit(monkeypatch):
    from app.modules.audit import service as audit

    monkeypatch.setattr(audit, "record", lambda *args, **kwargs: None)


def _step(executor, request, expected_status, event_type):
    before = len(executor.calls)
    res = request()
    assert res.status_code == expected_status, res.text
    new = executor.calls[before:]
    assert [call[0] for call in new] == [event_type]
    return res, new[0][1]


def test_user_create_fires_user_created(test_client, db_session, admin_user, executor, quiet_audit):
    h = _headers(test_client)
    body = {"username": "ev-user", "password": "evpass1234"}
    res, data = _step(
        executor, lambda: test_client.post("/api/users", json=body, headers=h), 201, "user.created"
    )
    assert data == {"id": res.json()["id"], "username": "ev-user", "is_admin": False}


def test_connection_call_sites_fire_once(
    test_client, db_session, admin_user, executor, quiet_audit
):
    h = _headers(test_client)
    res, data = _step(
        executor,
        lambda: test_client.post(
            "/api/connections", json={"name": "ev-conn", "kind": "ssh"}, headers=h
        ),
        201,
        "connection.created",
    )
    cid = res.json()["id"]
    assert data["id"] == cid and data["name"] == "ev-conn"

    _, data = _step(
        executor,
        lambda: test_client.put(f"/api/connections/{cid}", json={"name": "ev-conn2"}, headers=h),
        200,
        "connection.updated",
    )
    assert data["id"] == cid and data["name"] == "ev-conn2"

    _, data = _step(
        executor,
        lambda: test_client.delete(f"/api/connections/{cid}", headers=h),
        204,
        "connection.deleted",
    )
    assert data["id"] == cid

    body = {"mode": "merge", "connections": [{"name": "imp", "kind": "ssh"}]}
    _, data = _step(
        executor,
        lambda: test_client.post("/api/connections/import", json=body, headers=h),
        200,
        "connections.imported",
    )
    assert data == {"count": 1, "mode": "merge"}


def test_server_create_and_update_fire_once(
    test_client, db_session, admin_user, executor, quiet_audit
):
    h = _headers(test_client)
    body = {"name": "ev-srv", "hostname": "ev.example"}
    res, data = _step(
        executor,
        lambda: test_client.post("/api/servers", json=body, headers=h),
        201,
        "server.created",
    )
    sid = res.json()["id"]
    assert data == {"id": sid, "name": "ev-srv", "hostname": "ev.example"}

    _, data = _step(
        executor,
        lambda: test_client.put(f"/api/servers/{sid}", json={"name": "ev-srv2"}, headers=h),
        200,
        "server.updated",
    )
    assert data == {"id": sid, "name": "ev-srv2"}


def test_playbook_call_sites_fire_once(test_client, db_session, admin_user, executor, quiet_audit):
    h = _headers(test_client)
    body = {"name": "Ev", "filename": "ev.yml", "content": "- hosts: all\n  tasks: []\n"}
    res, data = _step(
        executor,
        lambda: test_client.post("/api/ansible/playbooks", json=body, headers=h),
        201,
        "playbook.created",
    )
    pid = res.json()["id"]
    assert data == {"id": pid, "name": "Ev"}

    _, data = _step(
        executor,
        lambda: test_client.put(f"/api/ansible/playbooks/{pid}", json={"name": "Ev2"}, headers=h),
        200,
        "playbook.updated",
    )
    assert data == {"id": pid, "name": "Ev2"}

    _, data = _step(
        executor,
        lambda: test_client.delete(f"/api/ansible/playbooks/{pid}", headers=h),
        204,
        "playbook.deleted",
    )
    assert data == {"id": pid, "name": "Ev2"}


def test_frp_config_call_sites_fire_once(
    test_client, db_session, admin_user, executor, quiet_audit, monkeypatch
):
    from app.modules.frp import config_router

    monkeypatch.setattr(config_router, "write_frps_config", lambda config, **kwargs: None)
    monkeypatch.setattr(config_router, "remove_frps_config", lambda: None)
    h = _headers(test_client)
    body = {"name": "Ev", "server_addr": "frps.example.net"}
    res, data = _step(
        executor,
        lambda: test_client.post("/api/frp/server-config", json=body, headers=h),
        201,
        "frp.config.created",
    )
    cid = res.json()["id"]
    assert data == {"id": cid, "name": "Ev"}

    _, data = _step(
        executor,
        lambda: test_client.put(f"/api/frp/server-config/{cid}", json={"name": "Ev2"}, headers=h),
        200,
        "frp.config.updated",
    )
    assert data == {"id": cid, "name": "Ev2"}

    _, data = _step(
        executor,
        lambda: test_client.delete(f"/api/frp/server-config/{cid}", headers=h),
        204,
        "frp.config.deleted",
    )
    assert data == {"id": cid, "name": "Ev2"}


def test_frp_tunnel_call_sites_fire_once(
    test_client, db_session, admin_user, executor, quiet_audit
):
    from app.modules.frp.models import FrpServerConfig
    from app.modules.servers.models import Server

    db_session.add(
        FrpServerConfig(
            id="cfg-ev", name="Ev", server_addr="frps.example.net", auth_token="ev-token"
        )
    )
    db_session.add(Server(id="srv-ev", name="ev-srv", hostname="ev.example.test"))
    db_session.commit()
    h = _headers(test_client)
    body = {
        "server_id": "srv-ev",
        "frp_config_id": "cfg-ev",
        "name": "ev-ssh",
        "tunnel_type": "stcp",
        "protocol": "ssh",
        "local_port": 22,
    }
    res, data = _step(
        executor,
        lambda: test_client.post("/api/frp/tunnels", json=body, headers=h),
        201,
        "frp.tunnel.created",
    )
    tid = res.json()["id"]
    assert data["id"] == tid and data["serverId"] == "srv-ev"

    _, data = _step(
        executor,
        lambda: test_client.put(f"/api/frp/tunnels/{tid}", json={"local_port": 2222}, headers=h),
        200,
        "frp.tunnel.updated",
    )
    assert data["id"] == tid

    _, data = _step(
        executor,
        lambda: test_client.delete(f"/api/frp/tunnels/{tid}", headers=h),
        204,
        "frp.tunnel.deleted",
    )
    assert data["id"] == tid
