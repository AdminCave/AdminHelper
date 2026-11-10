# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The row and advisory locks of the incidents, on real connections (R-1149).

A recovery locks every incident it may write in one id-ordered query, and an ack
holds only what it acks: the two never wait on each other in a circle. The
ingests of one key wait on its advisory lock, so they open one incident.

Two real connections each: the rows are removed at the end."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.modules.notifications import incidents, stream_hub
from app.modules.notifications.models import NotificationIncident
from app.modules.notifications.router import ack_incidents
from app.modules.notifications.schemas import IdsRequest, IncomingEvent
from app.modules.servers.models import Server
from app.modules.users.models import User

from .test_identity_revocation import _a_session_waits_for
from .test_notification_incidents import _check
from .test_notifications import _sub, _user

T0 = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)


def _at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture()
def world(pg_engine, monkeypatch):
    """Unique keys, a server and an admin; everything of them deleted afterwards."""
    monkeypatch.setattr(stream_hub, "publish", lambda *_a, **_k: None)
    tag = uuid.uuid4().hex[:8]
    new_session = sessionmaker(bind=pg_engine)
    server = f"srv-lock-{tag}"
    with new_session() as setup:
        setup.add(Server(id=server, name=f"lock{tag}", hostname=f"lock{tag}.local"))
        setup.commit()
        admin = _user(setup, f"lock-{tag}", is_admin=True, email=f"lock-{tag}@example.org")
        _sub(setup, admin, email=True)
        admin_id = admin.id
    keys = [f"check:lock-{tag}-{n}" for n in range(3)]
    yield new_session, server, keys, admin_id
    with pg_engine.begin() as conn:
        conn.execute(delete(NotificationIncident).where(NotificationIncident.source_id == server))
        conn.execute(delete(User).where(User.id == admin_id))
        conn.execute(delete(Server).where(Server.id == server))


def _ingest(new_session, event, minutes):
    with new_session() as session:
        incidents.ingest(session, event, now=_at(minutes))


def _pid(session) -> int:
    return session.execute(text("SELECT pg_backend_pid()")).scalar()


def _free(pg_engine, incident_id: int) -> bool:
    """Whether another connection could lock the incident right now."""
    with pg_engine.connect() as probe:
        try:
            probe.execute(
                text("SELECT id FROM notification_incident WHERE id = :i FOR UPDATE NOWAIT"),
                {"i": incident_id},
            )
        except OperationalError:
            return False
        finally:
            probe.rollback()
    return True


def _ids(new_session, server):
    with new_session() as session:
        return [
            (i.id, i.key, i.state)
            for i in session.query(NotificationIncident)
            .filter(NotificationIncident.source_id == server)
            .order_by(NotificationIncident.id)
        ]


def test_two_ingests_of_one_key_wait_on_its_lock_and_open_one_incident(pg_engine, world):
    new_session, server, (key, *_), _ = world
    holder = new_session()
    ex = ThreadPoolExecutor(max_workers=2)
    try:
        incidents._lock(holder, [key])
        first = ex.submit(_ingest, new_session, _check(key=key, server=server), 0)
        second = ex.submit(_ingest, new_session, _check(key=key, server=server), 1)
        pid = _pid(holder)
        assert _a_session_waits_for(pg_engine, pid), "the ingests must wait for the key's lock"
        assert not first.done() and not second.done()
        holder.rollback()
        first.result(10)
        second.result(10)
    finally:
        holder.close()
        ex.shutdown(wait=True)

    ((_, opened_key, state),) = _ids(new_session, server)
    assert (opened_key, state) == (key, "open")


def test_a_recovery_waiting_on_a_resolved_incident_does_not_hold_the_active_one_yet(
    pg_engine, world
):
    # The stale key's latest incident (resolved, smaller id) is held, as an ack held
    # it; the recovery waits for it before it locks the active incident with the
    # larger id, so an ack that holds the larger id first can still finish.
    new_session, server, (stale_key, active_key, _), _ = world
    _ingest(new_session, _check(key=stale_key, server=server), 0)
    _ingest(new_session, _check("ok", key=stale_key, server=server), 1)
    _ingest(new_session, _check(key=active_key, server=server), 2)
    (resolved_id, _, resolved), (active_id, _, active) = _ids(new_session, server)
    assert (resolved, active) == ("resolved", "open") and resolved_id < active_id

    recovery = IncomingEvent(
        event_type="monitoring.check.transition",
        severity="critical",
        category="monitoring",
        title="CPU ok",
        source_type="server",
        source_ids=[server, server],
        incident_keys=[active_key, stale_key],
        new_status="ok",
    )
    holder = new_session()
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        holder.execute(
            text("SELECT id FROM notification_incident WHERE id = :i FOR UPDATE"),
            {"i": resolved_id},
        )
        recovering = ex.submit(_ingest, new_session, recovery, 3)
        assert _a_session_waits_for(pg_engine, _pid(holder)), "the recovery must wait"
        assert _free(pg_engine, active_id), "the active incident must not be held yet"
        holder.rollback()
        recovering.result(10)
    finally:
        holder.close()
        ex.shutdown(wait=True)

    states = [state for _, _, state in _ids(new_session, server)]
    assert states == ["resolved", "resolved"]


def test_an_ack_does_not_hold_an_incident_it_skips(pg_engine, world):
    new_session, server, (key, *_), admin_id = world
    _ingest(new_session, _check(key=key, server=server), 0)
    _ingest(new_session, _check("ok", key=key, server=server), 1)
    ((resolved_id, _, state),) = _ids(new_session, server)
    assert state == "resolved"

    session = new_session()
    try:
        user = session.get(User, admin_id)
        out = ack_incidents(IdsRequest(ids=[resolved_id]), db=session, current_user=user)
        assert out == {"updated": 0, "skipped": [resolved_id]}
        # The transaction is still open: a held row would be held here.
        assert _free(pg_engine, resolved_id), "a skipped incident must not be held"
    finally:
        session.rollback()
        session.close()


def test_an_ack_decides_on_the_locked_look_not_on_the_unlocked_one(pg_engine, world, monkeypatch):
    # A recovery that resolves the incident between the unlocked look and the locked
    # one: the locked look must see the new state, the ack skips it.
    new_session, server, (key, *_), admin_id = world
    _ingest(new_session, _check(key=key, server=server), 0)
    ((open_id, _, state),) = _ids(new_session, server)
    assert state == "open"

    real_access = incidents.access

    def access(db, user, incident_id, lock=False):
        held = real_access(db, user, incident_id, lock=lock)
        if not lock:
            _ingest(new_session, _check("ok", key=key, server=server), 1)
        return held

    monkeypatch.setattr(incidents, "access", access)
    session = new_session()
    try:
        user = session.get(User, admin_id)
        out = ack_incidents(IdsRequest(ids=[open_id]), db=session, current_user=user)
        assert out == {"updated": 0, "skipped": [open_id]}
        session.commit()
    finally:
        session.close()

    ((_, _, state),) = _ids(new_session, server)
    assert state == "resolved"
