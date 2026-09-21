# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Schema-driven fuzzing of the issuer API under each way a caller can present itself.

Three contexts: no headers at all, a gateway verdict without a certificate, and a
verdict with a real certificate — the shapes /renew has to tell apart. The
issuer never terminates mTLS itself; it trusts `x-client-verify: SUCCESS` plus
the escaped PEM the gateway forwards, so those headers ARE the credential here
and fuzzing them is fuzzing the auth boundary.

Like the other two services, `ignored_auth` is not in the check list: it counts
only security parameters the schema declares, and this app declares none (the
headers are read straight from the request). With nothing to strip it degrades
to "any 2xx is a failure", which says nothing about authentication. The real
rejection paths are pinned by hand in test_enroll_renew.py.
"""

from __future__ import annotations

import datetime
import os
import tomllib
import urllib.parse
from pathlib import Path

import pytest
import schemathesis
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import (
    ensure_resource_availability,
    negative_data_rejection,
    response_schema_conformance,
    use_after_free,
)

from app import config, pki
from app.main import app
from app.tokens import InMemoryTokenStore

_EXCLUDE_FILE = Path(__file__).parent / "schemathesis_exclude.toml"


def _excluded_operation_ids(known: set[str]) -> list[str]:
    """Reads the exclusion list and checks every id against the live schema.

    An id the schema does not know excludes nothing and says nothing, so it is an
    error rather than a silent no-op.
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


# from_dict + .app rather than from_asgi: from_asgi fetches the schema over the
# transport and runs the application lifespan at import time.
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
    use_after_free,
    ensure_resource_availability,
]

MAX_EXAMPLES = int(os.environ.get("AH_SCHEMATHESIS_EXAMPLES", "5"))


def _client_cert_pem() -> str:
    """A self-signed leaf standing in for what the gateway would forward."""
    key = pki.generate_key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "schemathesis-client")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2026, 1, 1))
        .not_valid_after(datetime.datetime(2027, 1, 1))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.fixture()
def auth_headers():
    """A fresh in-memory token store per test, plus the three header shapes.

    The TestClient context manager is what builds app.state.issuer — the lifespan
    creates it, and without entering it here the state would not exist yet
    (schemathesis starts the lifespan only on its first request). The store is
    then swapped rather than cleared: no coupling to its internals, and nothing a
    generated /enroll call writes can leak into the next test.
    """
    from fastapi.testclient import TestClient

    with TestClient(app):
        store = InMemoryTokenStore()
        app.state.issuer.tokens = store
        app.state.token_store = store

        yield {
            "anonymous": {},
            "verified_without_cert": {config.HEADER_VERIFY: "SUCCESS"},
            "verified_with_cert": {
                config.HEADER_VERIFY: "SUCCESS",
                config.HEADER_CERT: urllib.parse.quote(_client_cert_pem()),
            },
        }


@pytest.mark.schemathesis
@pytest.mark.parametrize("context", ["anonymous", "verified_without_cert", "verified_with_cert"])
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
