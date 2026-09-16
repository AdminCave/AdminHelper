# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SSRF guard parity server <-> monitoring (harness 8a, T5).

apps/server/app/core/ssrf.py says "Mirrors the monitoring service's guard" — and
had drifted: the monitoring copy caps DNS resolution with a hard deadline, the
server copy did not, so a hung resolver blocked the webhook path until the OS
default gave up. A promise in a docstring is not a guard; this test is.

Compared is the code, with docstrings and comments removed: the two modules
legitimately explain themselves differently (different callers, different threat
text) but must behave identically. ast.unparse does the normalizing, so neither
formatting nor a reflowed comment can make this test rot.
"""

import ast
import difflib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SERVER = _ROOT / "apps" / "server" / "app" / "core" / "ssrf.py"
_MONITORING = _ROOT / "apps" / "monitoring" / "app" / "core" / "ssrf.py"

# Deliberate, justified divergences as (regex, reason). Empty is the goal: every
# entry is a hole in the guard, so the cap is low on purpose — a fourth one means
# the two files stopped being one implementation and the claim in the docstring
# has to go instead.
_ALLOWED_DIVERGENCES: list[tuple[str, str]] = []


def _strip_docstrings(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]


def _normalized(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    _strip_docstrings(tree)
    ast.fix_missing_locations(tree)
    lines = ast.unparse(tree).splitlines()
    if _ALLOWED_DIVERGENCES:
        import re

        patterns = [re.compile(p) for p, _ in _ALLOWED_DIVERGENCES]
        lines = [ln for ln in lines if not any(p.search(ln) for p in patterns)]
    return lines


def test_allowlist_stays_small():
    assert len(_ALLOWED_DIVERGENCES) <= 3, (
        f"too many accepted divergences ({len(_ALLOWED_DIVERGENCES)}) — at that point the two "
        f"guards are not one implementation any more: {[r for _, r in _ALLOWED_DIVERGENCES]}"
    )


def test_server_and_monitoring_ssrf_guards_are_identical():
    server = _normalized(_SERVER)
    monitoring = _normalized(_MONITORING)

    # Non-empty guard: a parse that yields a stub would compare nothing at all.
    # The normalized guard is 63 lines today; 25 leaves room for a small edit
    # without leaving room for an empty comparison.
    assert len(server) >= 25, f"server guard normalized to only {len(server)} lines"
    assert len(monitoring) >= 25, f"monitoring guard normalized to only {len(monitoring)} lines"

    if server != monitoring:
        diff = list(
            difflib.unified_diff(
                monitoring, server, fromfile="apps/monitoring", tofile="apps/server", lineterm=""
            )
        )
        raise AssertionError(
            "SSRF guards drifted (docstrings and comments already ignored):\n"
            + "\n".join(diff[:40])
        )
