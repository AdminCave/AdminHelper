# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Schema-driven fuzzing of the whole API, once per authentication context.

Every route is called with inputs generated from its own OpenAPI schema, under
each of the five ways a caller can present itself: an admin JWT, a read key, a
read-write key, a key bound to a *different* server, and the internal
service-to-service key. Two bug classes come out of this that no hand-written
test finds: a shape the route never considered (a 500 where the schema promises
a 4xx), and a route that answers a caller it should have rejected — that is what
`ignored_auth` looks for, by repeating each call with the credentials stripped.

Everything runs in-process against the app's ASGI transport and the test
database; there is no server to start and nothing outside this process is
touched. Excluded operations live in schemathesis_exclude.toml, one entry with a
reason each — never a flag in a script, so an exclusion stays visible.
"""

import os
import tomllib
from pathlib import Path

import pytest
import schemathesis
from hypothesis import HealthCheck, settings

# not_a_server_error is the only check with a home in the public namespace; in
# 4.27 the OpenAPI-specific ones exist solely under specs.openapi.
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import (
    ensure_resource_availability,
    ignored_auth,
    negative_data_rejection,
    response_schema_conformance,
    use_after_free,
)

from app.core.auth import hash_api_key
from app.core.database import get_db
from app.main import app
from app.modules.api_keys.models import ApiKey
from app.modules.servers.models import Server

_EXCLUDE_FILE = Path(__file__).parent / "schemathesis_exclude.toml"
# The other server in the matrix: the bound key belongs to this one, so every
# request it makes against any other server's route is an IDOR attempt.
_FOREIGN_SERVER_ID = "srv-schemathesis-foreign"


def _excluded_operation_ids(known: set[str]) -> list[str]:
    """Reads the exclusion list and checks every id against the live schema.

    Missing file -> no exclusions. Malformed file, or an id the schema does not
    know -> hard error. The second half is not pedantry: a typo in an id excludes
    nothing and says nothing, so the operation keeps being fuzzed while the file
    claims it is handled — which is how a documented 500 stayed unguarded here
    once already. An id that no longer exists is the same signal from the other
    direction: the route is gone and its entry is dead weight.
    """
    if not _EXCLUDE_FILE.exists():
        return []
    data = tomllib.loads(_EXCLUDE_FILE.read_text(encoding="utf-8"))
    ids = []
    for entry in data.get("exclude", []):
        if not entry.get("operation_id") or not entry.get("reason"):
            raise ValueError(f"{_EXCLUDE_FILE.name}: every entry needs operation_id and reason")
        ids.append(entry["operation_id"])
    unknown = sorted(set(ids) - known)
    if unknown:
        raise ValueError(
            f"{_EXCLUDE_FILE.name}: no such operation_id in the schema: {', '.join(unknown)}"
        )
    return ids


# from_dict + .app, NOT from_asgi: from_asgi fetches /openapi.json over the ASGI
# transport, which starts the application lifespan at *import* time — and this
# app's startup queries the users table, which the pg_engine fixture has not
# created yet when pytest collects. Taking the schema straight off the app object
# needs no request; the transport (and with it the lifespan, by then against a
# migrated database) is only used once a case is actually called.
_RAW_SCHEMA = app.openapi()
schema = schemathesis.openapi.from_dict(_RAW_SCHEMA)
schema.app = app
_KNOWN_OPERATION_IDS = {
    operation["operationId"]
    for path in _RAW_SCHEMA["paths"].values()
    for method, operation in path.items()
    if method in ("get", "post", "put", "patch", "delete") and "operationId" in operation
}
_EXCLUDED = _excluded_operation_ids(_KNOWN_OPERATION_IDS)
if _EXCLUDED:
    schema = schema.exclude(operation_id=_EXCLUDED)

CHECKS = [
    not_a_server_error,
    response_schema_conformance,
    negative_data_rejection,
    ignored_auth,
    use_after_free,
    ensure_resource_availability,
]

# 5 locally, 20 in the PR CI, 100 on the weekly box — scripts/tests/run.sh and
# heavy.sh set the budget, the suite only reads it.
MAX_EXAMPLES = int(os.environ.get("AH_SCHEMATHESIS_EXAMPLES", "5"))


@pytest.fixture()
def api_db(db_session, monkeypatch):
    """Points the app at the test session for the whole fuzzing run.

    The same override the test_client fixture installs, but the requests come
    from schemathesis instead of a TestClient. The outer transaction of
    db_session rolls everything the fuzzer wrote back at the end of the test.

    Unlike a TestClient the schemathesis transport DOES run the application
    lifespan — on the first request, once per process. Its startup would create
    the default admin through the real engine, outside this transaction and
    therefore past the rollback: the next test's admin_user fixture then dies on
    the unique username. The fixtures below own the test data, so startup has
    nothing left to set up here.
    """
    monkeypatch.setattr("app.main._run_startup_tasks", lambda: None)

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    yield db_session
    app.dependency_overrides.clear()


def _api_key(db, *, permission: str, server_id: str | None, name: str) -> str:
    raw = f"ah_schemathesis_{name}"
    db.add(
        ApiKey(
            name=name,
            hashed_key=hash_api_key(raw),
            permission=permission,
            server_id=server_id,
        )
    )
    db.commit()
    return raw


@pytest.fixture()
def auth_headers(api_db, admin_user, monkeypatch) -> dict[str, dict[str, str]]:
    """The five ways in: JWT, three kinds of API key, and the internal key.

    The token is signed directly instead of fetched from /api/auth/login: it is
    the same function the login endpoint calls, and the fixture runs once per
    generated operation — a bcrypt verify per test would cost more than the
    fuzzing it sets up (the admin_user fixture already pays for one hash).
    """
    from app.core.auth import create_access_token

    token = create_access_token({"sub": admin_user.username})

    api_db.add(
        Server(
            id=_FOREIGN_SERVER_ID,
            name="schemathesis-foreign",
            hostname="foreign.schemathesis.test",
        )
    )
    api_db.commit()

    # The internal key is read once at import into the router's own namespace, so
    # the value has to be patched there, not in the config module.
    internal = "schemathesis-internal-key"
    monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", internal)

    return {
        "admin_jwt": {"Authorization": f"Bearer {token}"},
        "read_key": {"X-API-Key": _api_key(api_db, permission="read", server_id=None, name="read")},
        "read_write_key": {
            "X-API-Key": _api_key(api_db, permission="read_write", server_id=None, name="rw")
        },
        "foreign_bound_key": {
            "X-API-Key": _api_key(
                api_db,
                permission="read_write",
                server_id=_FOREIGN_SERVER_ID,
                name="bound-elsewhere",
            )
        },
        "internal_key": {"X-Internal-Key": internal},
    }


@pytest.mark.schemathesis
@pytest.mark.parametrize(
    "context",
    ["admin_jwt", "read_key", "read_write_key", "foreign_bound_key", "internal_key"],
)
@schema.parametrize()
@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    # Without this the suite is a different suite on every run: pytest-randomly
    # reseeds Hypothesis per run, so one run is green and the next one red on an
    # operation nobody touched — a gate that flickers proves nothing. The weekly
    # box run searches deeper through AH_SCHEMATHESIS_EXAMPLES, not through luck.
    derandomize=True,
    # The database fixture is function-scoped and shared by every example of one
    # test, which is exactly what this health check exists to warn about. The
    # warning is earned, not a formality: shared state between examples is how one
    # rejected statement poisons the rest. Suppressing it is right — the fixture is
    # expensive and the test rolls back after every example (see below) — but the
    # rollback is the reason it is safe, not the suppression.
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_api_under_every_auth_context(case, context, auth_headers, api_db):
    try:
        case.call_and_validate(headers=auth_headers[context], checks=CHECKS)
    finally:
        # One db_session serves every example of this test, and a statement that
        # Postgres rejects (an integer too large for the column, a NUL byte in a
        # text value) aborts the transaction for all of them: the next example
        # then fails on "current transaction is aborted" instead of on its own
        # merits, and whether a run is green depends on the order pytest-randomly
        # picked. Rolling back to the savepoint after each example is what makes
        # the examples independent — derandomize only fixes the DATA, not the state.
        api_db.rollback()
