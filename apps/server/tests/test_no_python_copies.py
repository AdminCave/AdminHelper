# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""No new copies between the services (R-0698): a helper both need lives in apps/pycommon
(ah_common). Two functions of the same name, arguments and body (docstrings dropped) in
apps/server/app and apps/monitoring/app are a copy."""

import ast
from collections import defaultdict
from pathlib import Path

_APPS = Path(__file__).resolve().parents[2]
_TREES = (_APPS / "server" / "app", _APPS / "monitoring" / "app")

# Known copies, per pair of modules: the names that may stay doubled until their row is built.
_KNOWN = {
    ("monitoring/app/mail_template.py", "server/app/modules/notifications/mail_template.py"): {
        "_fill",
        "_html_values",
        "compose",
        "format_time",
        "unknown",
    },
}  # R-1740: into ah_common


def _shape(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    body = fn.body
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        body = body[1:]
    module = ast.Module(body=body, type_ignores=[])
    return f"{type(fn).__name__}|{ast.dump(fn.args)}|{ast.dump(module)}"


def _copies() -> dict[tuple[str, ...], set[str]]:
    seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    for tree in _TREES:
        files = sorted(tree.rglob("*.py"))
        assert files, f"no Python files under {tree.relative_to(_APPS)}"
        for path in files:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    seen[(node.name, _shape(node))].add(path.relative_to(_APPS).as_posix())
    copies: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for (name, _), paths in seen.items():
        if len({p.split("/")[0] for p in paths}) > 1:
            copies[tuple(sorted(paths))].add(name)
    return copies


def test_no_function_is_copied_between_server_and_monitoring():
    new = {
        pair: sorted(names - _KNOWN.get(pair, set()))
        for pair, names in _copies().items()
        if names - _KNOWN.get(pair, set())
    }
    assert not new, f"move these into apps/pycommon/ah_common instead of copying: {new}"


def test_known_copies_are_still_copies():
    # A known copy that was merged or drifted apart leaves the list, so it cannot hide a
    # new one later.
    copies = _copies()
    stale = {
        pair: sorted(names - copies.get(pair, set()))
        for pair, names in _KNOWN.items()
        if names - copies.get(pair, set())
    }
    assert not stale, f"no longer copies, drop them from _KNOWN: {stale}"


def test_the_guard_sees_a_copy():
    # Positive control for _shape: the same function with another docstring is a copy, a
    # changed body is not.
    a = ast.parse('def f(x):\n    """one"""\n    return x + 1\n').body[0]
    b = ast.parse('def f(x):\n    """two"""\n    return x + 1\n').body[0]
    c = ast.parse("def f(x):\n    return x + 2\n").body[0]
    assert _shape(a) == _shape(b)
    assert _shape(a) != _shape(c)
