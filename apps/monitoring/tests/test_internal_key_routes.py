# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every route of the monitoring service but /health and /health/detail answers a request
without a key with 401 (R-1792). The routers attach require_internal or require_agent per
route, not per router, so a new route that forgets it would be open to anyone who reaches
the service; this walks the app's routes, so it covers routes nobody wrote a test for."""

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

# Reachable without a key on purpose: the liveness probe, and the numbers for the
# monitoring of AdminHelper itself, which neither the gateway nor the server forwards.
_OPEN = {("GET", "/health"), ("GET", "/health/detail")}


def _api_routes(node, prefix=""):
    """Every APIRoute below a node. FastAPI from 0.138 wraps an included router in an
    _IncludedRouter without .routes; its routes sit behind include_context."""
    if isinstance(node, APIRoute):
        yield prefix, node
        return
    sub = getattr(node, "routes", None)
    ctx = getattr(node, "include_context", None)
    if not sub and ctx is not None:
        prefix += ctx.prefix
        sub = ctx.included_router.routes
    for child in sub or ():
        yield from _api_routes(child, prefix)


def _routes():
    from app.main import app

    for prefix, route in _api_routes(app.router):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, prefix + route.path


@pytest.fixture()
def client(db_engine):
    from app.core.database import get_db
    from app.main import app

    factory = sessionmaker(bind=db_engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_walk_sees_the_routes():
    routes = set(_routes())
    # A walk that found nothing would pass every route below.
    assert len(routes) > 50
    assert _OPEN <= routes


@pytest.mark.parametrize("method,path", sorted(set(_routes()) - _OPEN))
def test_a_request_without_a_key_gets_401(client, method, path):
    url = re.sub(r"\{[^}]+\}", "x", path)

    response = client.request(method, url, json={})

    assert response.status_code == 401, (method, path, response.text[:200])


def test_the_open_route_answers_without_a_key(client):
    assert client.get("/health").status_code == 200
