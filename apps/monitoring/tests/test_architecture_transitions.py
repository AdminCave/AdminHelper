# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The status-transition pipeline lives in check_engine only (harness 8a, T4).

Two paths produce check results — the scheduler (check_engine.execute_check) and
the agent push ingest (routers/agent.py). The read-modify-write between them
(damping, effective status, transition log, sent-state decision) used to exist
twice; the copy in agent.py had already drifted in how it stored details (audit
B3). One implementation is the fix, and this guard is what keeps a second one
from growing back: a text scan, because a duplicate is invisible to any
behavioural test — both copies pass.
"""

import ast
import re
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent / "app"
_ENGINE = _APP / "check_engine.py"

# The pipeline's building blocks. A second caller of these outside the engine is
# a second pipeline — that is the drift this test exists for.
_ENGINE_ONLY = (
    "next_fail_count(",
    "effective_status(",
    "is_suppressed(",
    "\"Check '%s': %s -> %s (%s)\"",
)

# The pure helpers by bare name. Importing one outside the engine is the start of
# a second pipeline even when the call site is aliased (`… as nfc`), which the
# token scan below would never see.
_PIPELINE_NAMES = {"next_fail_count", "effective_status", "is_suppressed"}


def _imports_a_pipeline_helper(source: str) -> bool:
    """True if the module imports one of the pure helpers from check_engine.

    Parsed rather than matched: the import is routinely wrapped across lines by
    ruff at line-length 100, and a regex that only sees single-line imports would
    quietly stop covering exactly the form the formatter produces.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.check_engine":
            if any(alias.name in _PIPELINE_NAMES for alias in node.names):
                return True
    return False


def _app_sources() -> dict[Path, str]:
    return {
        py: py.read_text(encoding="utf-8")
        for py in sorted(_APP.rglob("*.py"))
        if "__pycache__" not in py.parts
    }


def test_scan_actually_reads_the_engine():
    """Non-empty guard: an empty or renamed engine would make every assertion
    below vacuously true."""
    sources = _app_sources()
    assert len(sources) >= 10, f"source scan found only {len(sources)} modules"
    assert _ENGINE in sources, "check_engine.py not found by the scan"
    engine = sources[_ENGINE]
    for token in _ENGINE_ONLY:
        assert token in engine, f"{token} no longer present in check_engine.py"
    assert "def apply_result(" in engine, "check_engine.apply_result is gone"


def test_transition_pipeline_only_in_check_engine():
    offenders: dict[str, list[str]] = {}
    for path, source in _app_sources().items():
        if path == _ENGINE:
            continue
        # Import lines are scanned separately: a call aliased at import time
        # (`from app.check_engine import next_fail_count as nfc`) carries neither
        # the bare name nor `next_fail_count(` at the call site.
        body = "\n".join(
            line for line in source.splitlines() if not line.startswith(("from ", "import "))
        )
        hits = [token for token in _ENGINE_ONLY if token in body]
        if _imports_a_pipeline_helper(source):
            hits.append("imports a pipeline helper from check_engine")
        if hits:
            offenders[str(path.relative_to(_APP.parent))] = hits
    assert offenders == {}, (
        f"the transition pipeline is duplicated outside check_engine.py: {offenders}"
    )


def test_alert_dispatch_is_defined_once():
    definitions = [
        str(path.relative_to(_APP.parent))
        for path, source in _app_sources().items()
        if re.search(r"^def _dispatch_alert_bg\(", source, re.M)
    ]
    assert definitions == ["app/check_engine.py"], (
        f"_dispatch_alert_bg must exist exactly once, found in: {definitions}"
    )
