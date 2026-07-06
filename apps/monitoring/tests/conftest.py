# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test setup for the monitoring component.

Deliberately NO Postgres/testcontainers: only pure-logic tests run here
(line-protocol escaping, alert filter/cooldown, check status transitions).
The modules under test pull a writable DATA_DIR via app.core.config (creating
an .api_key there if needed) — so redirect it to a tmp directory before every
import.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATA_DIR", os.path.join(tempfile.gettempdir(), "adminhelper-monitor-test"))
# Disable the notification-hub push by default — these are pure-logic tests with
# no server to reach; the hub-emit tests set the URL explicitly.
os.environ.setdefault("SERVER_HUB_URL", "")


@pytest.fixture()
def client_db(monkeypatch):
    """Shared TestClient against the real app on sqlite: agent auth bypassed, VictoriaMetrics writes and
    the background-dispatch SessionLocal pointed at the test DB. Centralized here so new endpoint suites
    don't each carry a near-identical copy (6.131). The pre-existing suites (test_agent_report,
    test_service_process_checker, test_pagination) still define their own local copies for now.

    App imports stay lazy inside the fixture so DATA_DIR (set above) is in place before the app boots.
    """
    import app.core.database as database_mod
    from app.core import victoria as victoria_mod
    from app.core.auth import require_agent, require_internal
    from app.core.database import get_db
    from app.main import app
    from app.models import Base

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
    app.dependency_overrides[require_agent] = lambda: "srv-1"
    app.dependency_overrides[require_internal] = lambda: None
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: None)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)

    yield TestClient(app), factory

    app.dependency_overrides.clear()
