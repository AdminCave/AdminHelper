# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1744: GET /api/health answers without auth and without the database."""

import pytest

from app.core import database
from app.main import app


def test_health_answers_ok_without_auth(test_client):
    r = test_client.get("/api/health")

    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_does_not_touch_the_database(test_client, monkeypatch):
    def _no_db():
        raise AssertionError("/api/health opened a database session")
        yield  # pragma: no cover

    def _no_session(*args, **kwargs):
        raise AssertionError("/api/health opened a database session")

    app.dependency_overrides[database.get_db] = _no_db
    monkeypatch.setattr(database, "SessionLocal", _no_session)

    r = test_client.get("/api/health")

    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/api/healthz", "/api/health/x"])
def test_other_api_paths_still_answer_404(test_client, path):
    assert test_client.get(path).status_code == 404
