# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backwards-compatible pagination (audit P4) for the monitoring list
endpoints /checks, /status and /alerts.

Pinned per endpoint: (a) no params = full list (legacy behaviour),
(b) limit/offset slice in SQL + X-Total-Count carries the total,
(c) limit=0 / negative values are rejected with 422."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import require_internal
from app.core.database import get_db
from app.models import Base, MonitorAlertRule, MonitorCheck, MonitorState

INVALID_QUERIES = ("limit=0", "limit=-1", "limit=1001", "offset=-1")


@pytest.fixture()
def client_db():
    """TestClient against the real app with sqlite, internal auth bypassed."""
    from app.main import app

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_internal] = lambda: None

    yield TestClient(app), factory

    app.dependency_overrides.clear()


def _seed_checks(factory, n: int = 5) -> None:
    with factory() as db:
        for i in range(n):
            db.add(
                MonitorCheck(
                    id=f"chk-{i}",
                    server_id="srv-1",
                    name=f"check-{i}",
                    check_type="ping",
                    config="{}",
                    enabled=True,
                )
            )
            db.add(MonitorState(check_id=f"chk-{i}", status="ok"))
        db.commit()


def _seed_rules(factory, n: int = 5) -> None:
    with factory() as db:
        for i in range(n):
            db.add(
                MonitorAlertRule(
                    id=f"rule-{i}",
                    name=f"rule-{i}",
                    channel="webhook",
                    channel_config="{}",
                    enabled=True,
                )
            )
        db.commit()


class TestChecksPagination:
    def test_no_params_returns_full_list(self, client_db):
        client, factory = client_db
        _seed_checks(factory)
        r = client.get("/checks")
        assert r.status_code == 200, r.text
        assert [c["name"] for c in r.json()] == [f"check-{i}" for i in range(5)]
        assert r.headers["X-Total-Count"] == "5"

    def test_limit_offset_slice(self, client_db):
        client, factory = client_db
        _seed_checks(factory)
        r = client.get("/checks?limit=2&offset=1")
        assert r.status_code == 200, r.text
        body = r.json()
        assert [c["name"] for c in body] == ["check-1", "check-2"]
        # State join still works on the paginated page
        assert all(c["state"]["status"] == "ok" for c in body)
        assert r.headers["X-Total-Count"] == "5"

    def test_total_respects_server_filter(self, client_db):
        client, factory = client_db
        _seed_checks(factory)
        with factory() as db:
            db.add(
                MonitorCheck(
                    id="chk-x",
                    server_id="srv-2",
                    name="other",
                    check_type="ping",
                    config="{}",
                    enabled=True,
                )
            )
            db.commit()
        r = client.get("/checks?server_id=srv-1&limit=2")
        assert r.status_code == 200, r.text
        assert len(r.json()) == 2
        # Total = filtered set (5 of srv-1), not the full table (6)
        assert r.headers["X-Total-Count"] == "5"

    def test_invalid_params_rejected(self, client_db):
        client, _ = client_db
        for q in INVALID_QUERIES:
            r = client.get(f"/checks?{q}")
            assert r.status_code == 422, f"{q}: {r.status_code} {r.text}"


class TestStatusPagination:
    def test_no_params_returns_full_list(self, client_db):
        client, factory = client_db
        _seed_checks(factory)
        r = client.get("/status")
        assert r.status_code == 200, r.text
        assert [c["name"] for c in r.json()] == [f"check-{i}" for i in range(5)]
        assert r.headers["X-Total-Count"] == "5"

    def test_limit_offset_slice(self, client_db):
        client, factory = client_db
        _seed_checks(factory)
        r = client.get("/status?limit=2&offset=3")
        assert r.status_code == 200, r.text
        assert [c["name"] for c in r.json()] == ["check-3", "check-4"]
        assert r.headers["X-Total-Count"] == "5"

    def test_invalid_params_rejected(self, client_db):
        client, _ = client_db
        for q in INVALID_QUERIES:
            r = client.get(f"/status?{q}")
            assert r.status_code == 422, f"{q}: {r.status_code} {r.text}"


class TestAlertRulesPagination:
    def test_no_params_returns_full_list(self, client_db):
        client, factory = client_db
        _seed_rules(factory)
        r = client.get("/alerts")
        assert r.status_code == 200, r.text
        assert [a["name"] for a in r.json()] == [f"rule-{i}" for i in range(5)]
        assert r.headers["X-Total-Count"] == "5"

    def test_limit_offset_slice(self, client_db):
        client, factory = client_db
        _seed_rules(factory)
        r = client.get("/alerts?limit=2&offset=1")
        assert r.status_code == 200, r.text
        assert [a["name"] for a in r.json()] == ["rule-1", "rule-2"]
        assert r.headers["X-Total-Count"] == "5"

    def test_invalid_params_rejected(self, client_db):
        client, _ = client_db
        for q in INVALID_QUERIES:
            r = client.get(f"/alerts?{q}")
            assert r.status_code == 422, f"{q}: {r.status_code} {r.text}"


def test_status_summary_counts_per_status(client_db):
    # 5.21: the GROUP BY aggregation returns the same per-status tally as the old full row scan,
    # including statuses not present (0) and the total across all rows.
    client, factory = client_db
    with factory() as db:
        for i, st in enumerate(["ok", "ok", "warning", "critical", "critical", "critical"]):
            db.add(MonitorState(check_id=f"c{i}", status=st))
        db.commit()
    r = client.get("/status/summary")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "total": 6,
        "ok": 2,
        "warning": 1,
        "critical": 3,
        "unknown": 0,
        "pending": 0,
    }
