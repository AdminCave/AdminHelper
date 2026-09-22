# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Schema-driven fuzzing of the monitoring API under every authentication context.

Same shape as the server's suite (apps/server/tests/test_schemathesis.py), with
this service's three ways in: an agent key from the database, the shared internal
key, and no credentials at all.

Note what this suite does NOT reuse: the client_db fixture overrides require_agent
and require_internal with lambdas, which is right for endpoint tests but would
make an auth matrix meaningless — every context would be the same context. Here
the real dependencies run and the keys are real.

What the matrix does NOT buy here: `ignored_auth`, which is therefore left out of
the check list below (see the comment there). The value of running every
operation three times lies in the remaining five checks plus the different status
each context gets; auth enforcement itself is pinned by the hand-written tests.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import (
    ensure_resource_availability,
    negative_data_rejection,
    response_schema_conformance,
    use_after_free,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app

_EXCLUDE_FILE = Path(__file__).parent / "schemathesis_exclude.toml"
_INTERNAL_KEY = "schemathesis-internal-key"
_AGENT_KEY = "schemathesis-agent-key"
_AGENT_SERVER_ID = "srv-schemathesis"


def _read_exclusions(known: set[str], by_name: dict) -> tuple[dict[str, list], list[str]]:
    """Reads the exclusion list. Returns (waived checks per operation, dropped operations).

    Per check, not per operation — the same two kinds the server's suite uses (the
    three services share no test package, so the rule is spelled out per suite
    rather than imported across them). Taking an operation out wholesale waives
    not_a_server_error along with everything else, and that is the check that
    finds the 500s.

    Missing file -> nothing waived. A malformed entry, an id the schema does not
    know, or a check this suite does not run -> hard error: a typo waives nothing
    and says nothing, so the file would claim a handling that does not exist.
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
            # operation honest.
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


# from_dict + .app rather than from_asgi, for the reason spelled out in the
# server's suite: from_asgi runs the application lifespan at import time.
_RAW_SCHEMA = app.openapi()
schema = schemathesis.openapi.from_dict(_RAW_SCHEMA)
schema.app = app

# ignored_auth is NOT in this list. It repeats each call without credentials and
# expects a rejection, but counts only security parameters the SCHEMA declares —
# and this app declares none at all (no securitySchemes, no security on any
# operation); core/auth.py reads X-API-Key and X-Internal-Key from the headers
# directly. With nothing to strip the check falls through to "any 2xx is a
# failure", which is not an auth verdict. Enforcement is pinned by the
# hand-written auth tests; running a check that cannot see the credentials would
# only produce findings about itself.
CHECKS = [
    not_a_server_error,
    response_schema_conformance,
    negative_data_rejection,
    use_after_free,
    ensure_resource_availability,
]
_KNOWN_OPERATION_IDS = {
    operation["operationId"]
    for path in _RAW_SCHEMA["paths"].values()
    for method, operation in path.items()
    if method in ("get", "post", "put", "patch", "delete") and "operationId" in operation
}
_WAIVED_BY_OPERATION, _DROPPED_OPERATIONS = _read_exclusions(
    _KNOWN_OPERATION_IDS, {check.__name__: check for check in CHECKS}
)
if _DROPPED_OPERATIONS:
    schema = schema.exclude(operation_id=_DROPPED_OPERATIONS)

MAX_EXAMPLES = int(os.environ.get("AH_SCHEMATHESIS_EXAMPLES", "5"))


@pytest.fixture()
def auth_headers(monkeypatch) -> dict[str, dict[str, str]]:
    """Real auth, not the bypassing overrides: sqlite for the data, real keys.

    INTERNAL_API_KEY is imported into app.core.auth by value, so it is patched
    there rather than in the config module.
    """
    from app.models import Base, MonitorAgentKey

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def _override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_db
    # Not every path goes through Depends(get_db): the background dispatch and the
    # health probe open their own session through SessionLocal, which would reach
    # for the real Postgres this service is configured against.
    import app.core.database as database_mod

    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr("app.core.auth.INTERNAL_API_KEY", _INTERNAL_KEY)

    session = factory()
    session.add(
        MonitorAgentKey(
            id="schemathesis-key",  # String PK without a default generator
            server_id=_AGENT_SERVER_ID,
            hashed_key=MonitorAgentKey.hash_key(_AGENT_KEY),
        )
    )
    session.commit()
    session.close()

    # VictoriaMetrics is a network dependency; the fuzzer must not reach for it.
    from app.core import victoria as victoria_mod

    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: None)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)

    yield {
        "agent_key": {"X-API-Key": _AGENT_KEY},
        "internal_key": {"X-Internal-Key": _INTERNAL_KEY},
        "anonymous": {},
    }

    # pop, not clear(): clear() removes EVERY override on the app, including
    # ones a neighbouring fixture installed. Take back only what this fixture set.
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.schemathesis
@pytest.mark.parametrize("context", ["agent_key", "internal_key", "anonymous"])
@schema.parametrize()
@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_api_under_every_auth_context(case, context, auth_headers):
    case.call_and_validate(  # A copy per example: the transport writes its own defaults (user-agent,
        # Accept, …) into the dict it is handed, and this one is shared by every
        # example of the test — without the copy the header set grows as the run
        # goes on and later examples are sent something the earlier ones were not.
        headers=dict(auth_headers[context]),
        checks=CHECKS,
        excluded_checks=_WAIVED_BY_OPERATION.get(
            case.operation.definition.raw.get("operationId") or "", []
        ),
    )
