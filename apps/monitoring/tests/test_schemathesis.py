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


def _excluded_operation_ids() -> list[str]:
    """Reads the exclusion list; a malformed entry is an error, not a silent skip."""
    if not _EXCLUDE_FILE.exists():
        return []
    data = tomllib.loads(_EXCLUDE_FILE.read_text(encoding="utf-8"))
    ids = []
    for entry in data.get("exclude", []):
        if not entry.get("operation_id") or not entry.get("reason"):
            raise ValueError(f"{_EXCLUDE_FILE.name}: every entry needs operation_id and reason")
        ids.append(entry["operation_id"])
    return ids


# from_dict + .app rather than from_asgi, for the reason spelled out in the
# server's suite: from_asgi runs the application lifespan at import time.
schema = schemathesis.openapi.from_dict(app.openapi())
schema.app = app
_EXCLUDED = _excluded_operation_ids()
if _EXCLUDED:
    schema = schema.exclude(operation_id=_EXCLUDED)

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

    app.dependency_overrides.clear()


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
    )
