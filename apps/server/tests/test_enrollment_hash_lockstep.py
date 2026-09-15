# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enrollment-token hash lockstep server <-> ca-issuer (harness 8a, T3).

The server mints an enrollment token, stores hash_api_key(raw) and hands the raw
token to the client; the ca-issuer looks the token up by its own _hash(). The two
hashes are never compared in code, so a change on one side does not fail to
compile — it fails to enroll, at runtime, with a "token unknown" that looks like
a client error. Pin both to the same formula.

The ca-issuer is a separate service with its own venv: its function is read as
text, not imported.
"""

import ast
import inspect
import re
from pathlib import Path

from app.core.auth import hash_api_key

_ROOT = Path(__file__).resolve().parents[3]
_CA_DB = _ROOT / "apps" / "ca-issuer" / "app" / "db.py"
_ENROLL_SERVICE = _ROOT / "apps" / "server" / "app" / "modules" / "enrollment" / "service.py"

# sha256("probe"), computed independently of the implementation under test.
_PROBE_DIGEST = "ba9c736f19e7f60b7f6764adb0b7908c0a2b394e09b6c09863528c7f2bc86095"


def _formula(source: str, func: str) -> str:
    """The body of `func`, normalized: docstring dropped, parameter renamed ARG.

    Comparing text rather than behaviour is the point — the two services never run
    in the same process, so only the source can testify that they agree. The
    comparison goes through ``ast`` rather than a regex so that a docstring, a
    comment or a reflowed line cannot report a hash drift that is not one, and so
    that the rename touches actual references to the parameter, not a string
    literal or an attribute that happens to share its name.

    Known limit: only the `@decorator` form of wrapping is rejected. Rebinding the
    name after the def (`_hash = wrap(_hash)`) would still read as unchanged here.
    """
    fn = next(
        (
            n
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.FunctionDef) and n.name == func
        ),
        None,
    )
    assert fn is not None, f"function {func} not found"
    # A decorator can replace the return value without the body changing a byte.
    assert not fn.decorator_list, f"{func} carries a decorator — it can change the digest silently"

    body = fn.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    assert body, f"function {func} has an empty body"

    assert fn.args.args, f"{func} takes no argument — nothing to normalize"
    arg = fn.args.args[0].arg
    module = ast.Module(body=body, type_ignores=[])
    for node in ast.walk(module):
        if isinstance(node, ast.Name) and node.id == arg:
            node.id = "ARG"
    return ast.unparse(module)


def test_server_and_issuer_hash_enrollment_tokens_identically():
    server_formula = _formula(inspect.getsource(hash_api_key), "hash_api_key")
    issuer_formula = _formula(_CA_DB.read_text(encoding="utf-8"), "_hash")

    assert "sha256" in server_formula, f"unexpected server hash body: {server_formula}"
    assert server_formula == issuer_formula, (
        f"the two enrollment-token hashes are no longer the same formula — "
        f"server hash_api_key: {server_formula!r}, ca-issuer _hash: {issuer_formula!r}"
    )


def test_hash_api_key_is_plain_sha256_hex():
    """A digest the ca-issuer can reproduce without importing anything: if this
    value ever changes, every token minted before the change stops enrolling."""
    assert hash_api_key("probe") == _PROBE_DIGEST


def test_enrollment_service_stores_the_shared_hash():
    source = _ENROLL_SERVICE.read_text(encoding="utf-8")
    assert re.search(r"hashed_token\s*=\s*hash_api_key\(", source), (
        "enrollment/service.py no longer stores hashed_token via hash_api_key() — "
        "the lockstep above then guards a function nobody uses"
    )


def test_issuer_looks_tokens_up_through_the_shared_hash():
    """The other half of the same argument: equal formulas are worthless if the
    issuer stops running the token through _hash before the lookup."""
    source = _CA_DB.read_text(encoding="utf-8")
    assert re.search(r"hashed_token\s*==\s*_hash\(", source), (
        "ca-issuer db.py no longer looks enrollment tokens up via _hash() — "
        "the lockstep above then guards a function nobody uses"
    )
