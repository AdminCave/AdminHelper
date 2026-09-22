# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Schema-driven fuzzing of the whole API, once per authentication context.

Every route is called with inputs generated from its own OpenAPI schema, under
each of the four ways a caller can present itself: an admin JWT, a read key, a
read-write key, and the internal service-to-service key.

A fifth context — a key bound to a DIFFERENT server — was dropped after it turned
out to prove nothing: schemathesis generates random server_id path parameters and
never hits an existing one, so that context answered 403 exactly like the others.
The property it was meant to cover (a bound key may not reach another server's
data) is enforced in two places, and each has its own hand-written test with the
ids actually seeded: frp/provision_router.py::_require_server_scope in
tests/test_frp_provision_authz.py, and the scope filter in connections/router.py
in tests/test_connections_isolation.py. Two bug classes come out of this that no hand-written
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

_EXCLUDE_FILE = Path(__file__).parent / "schemathesis_exclude.toml"


def _read_exclusions(known: set[str], by_name: dict) -> tuple[dict[str, list], list[str]]:
    """Reads the exclusion list. Returns (waived checks per operation, dropped operations).

    Per check, not per operation. Taking an operation out wholesale would waive
    not_a_server_error along with everything else — and that is the check that
    finds the 500s, on exactly the write routes most entries here are about.

    Missing file -> nothing waived. A malformed entry, an id the schema does not
    know, or a check this suite does not run -> hard error. A typo waives nothing
    and says nothing, so the file would claim a handling that does not exist —
    which is how a documented 500 stayed unguarded here once already.
    """
    if not _EXCLUDE_FILE.exists():
        return {}, []
    data = tomllib.loads(_EXCLUDE_FILE.read_text(encoding="utf-8"))
    waived: dict[str, list] = {}
    dropped: list[str] = []
    for entry in data.get("exclude", []):
        operation_id, reason = entry.get("operation_id"), entry.get("reason")
        if not operation_id or not reason:
            raise ValueError(f"{_EXCLUDE_FILE.name}: every entry needs operation_id and reason")
        if entry.get("raises"):
            if entry.get("checks"):
                raise ValueError(
                    f"{_EXCLUDE_FILE.name}: {operation_id} has both `raises` and `checks` — "
                    "they mean different things (no response at all vs. a response one check "
                    "objects to), so one of them is wrong"
                )
            # The call dies on an uncaught exception before a response exists, so
            # no check can look at anything. Only here is dropping the whole
            # operation honest — and every one of these is a real product fault.
            dropped.append(operation_id)
            continue
        names = entry.get("checks")
        if not names:
            raise ValueError(
                f"{_EXCLUDE_FILE.name}: {operation_id} needs a non-empty `checks` list, or "
                "`raises = true` if the call itself throws — waiving a whole operation "
                "otherwise would silence not_a_server_error with it"
            )
        unknown_checks = sorted(set(names) - set(by_name))
        if unknown_checks:
            raise ValueError(
                f"{_EXCLUDE_FILE.name}: {operation_id} names checks this suite does not run: "
                f"{', '.join(unknown_checks)}"
            )
        waived.setdefault(operation_id, []).extend(by_name[n] for n in names)
    unknown = sorted((set(waived) | set(dropped)) - known)
    if unknown:
        raise ValueError(
            f"{_EXCLUDE_FILE.name}: no such operation_id in the schema: {', '.join(unknown)}"
        )
    return waived, dropped


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
CHECKS = [
    not_a_server_error,
    response_schema_conformance,
    negative_data_rejection,
    ignored_auth,
    use_after_free,
    ensure_resource_availability,
]

# 5 locally and in the PR CI — a different budget searches different data, so a
# CI failure would be one nobody can reproduce on their box. 100 on the weekly
# run; scripts/tests/run.sh and heavy.sh set it, the suite only reads it.
MAX_EXAMPLES = int(os.environ.get("AH_SCHEMATHESIS_EXAMPLES", "5"))

# ignored_auth repeats each call with the credentials stripped and expects a
# rejection — but it only counts security parameters the SCHEMA declares, and this
# app declares HTTPBearer alone (core/auth.py reads X-API-Key and X-Internal-Key
# straight from the headers). For every context that does not send a bearer token
# the check finds nothing to strip and falls through to "any 2xx is a failure",
# which is not an auth verdict at all. It stays on for the JWT, where it works,
# and is excluded elsewhere rather than papered over by excluding whole
# operations — those would lose the other five checks too.
_BEARER_CONTEXTS = {"admin_jwt"}

_WAIVED_BY_OPERATION, _DROPPED_OPERATIONS = _read_exclusions(
    _KNOWN_OPERATION_IDS, {check.__name__: check for check in CHECKS}
)
if _DROPPED_OPERATIONS:
    schema = schema.exclude(operation_id=_DROPPED_OPERATIONS)


def _excluded_checks_for(context: str, operation_id: str | None) -> list:
    """Checks that say nothing for this call: the context's, plus the operation's."""
    waived = [] if context in _BEARER_CONTEXTS else [ignored_auth]
    waived.extend(_WAIVED_BY_OPERATION.get(operation_id or "", []))
    return waived


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
    # pop, not clear(): clear() removes EVERY override on the app, including
    # ones a neighbouring fixture installed. Take back only what this fixture set.
    app.dependency_overrides.pop(get_db, None)


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
        "internal_key": {"X-Internal-Key": internal},
    }


@pytest.mark.schemathesis
@pytest.mark.parametrize(
    "context",
    ["admin_jwt", "read_key", "read_write_key", "internal_key"],
)
@schema.parametrize()
@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    # Without this the suite is a different suite on every run: Hypothesis draws a
    # fresh seed each time, so one run is green and the next red on an operation
    # nobody touched (observed: `6 failed, 299 passed` right after a `305 passed`)
    # — a gate that flickers proves nothing. Depth comes from
    # AH_SCHEMATHESIS_EXAMPLES in the weekly run, not from luck.
    # The determinism reaches as far as the tree, not further: Hypothesis also feeds
    # the literals of every loaded source file into generation (its per-file cache
    # under .hypothesis/constants/), so an edited tree searches new ground rather
    # than replaying the old run. A finding that appears "out of nowhere" after an
    # unrelated edit is that, not flakiness.
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
        case.call_and_validate(
            # A copy per example: the transport writes its own defaults (user-agent,
            # Accept, …) into the dict it is handed, and this one is shared by every
            # example of the test — without the copy the header set grows as the run
            # goes on and later examples are sent something the earlier ones were not.
            headers=dict(auth_headers[context]),
            checks=CHECKS,
            excluded_checks=_excluded_checks_for(
                context, case.operation.definition.raw.get("operationId")
            ),
        )
    finally:
        # One db_session serves every example of this test, and a statement that
        # Postgres rejects (an integer too large for the column, a NUL byte in a
        # text value) aborts the transaction for all of them: the next example
        # then fails on "current transaction is aborted" instead of on its own
        # merits, and whether a run is green then depends on which example ran
        # first. Rolling back to the savepoint after each example is what makes
        # them independent — derandomize fixes the DATA, not the database state.
        api_db.rollback()
