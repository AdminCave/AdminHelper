# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hook examples call the worker's HTTP helpers with keywords the helpers accept.

docs/examples/*.py are the starting points admins copy into hook scripts. They run
inside script_worker.py, which binds http_get/http_post to _safe_http_get and
_safe_http_post. Neither takes **kwargs, so a keyword the signature does not name
is a TypeError at runtime. event_hook_notify.py passed json= and its except branch
logged that TypeError as a failed notification (R-0490). No test executes the
examples, so the drift stayed invisible; this one compares each call against the
signature the worker really injects.
"""

import ast
import inspect
from pathlib import Path

from app.modules.hooks import script_worker

_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLES_DIR = _ROOT / "docs" / "examples"

# Name in the hook namespace -> the function script_worker.main() binds to it.
_HELPERS = {
    "http_get": script_worker._safe_http_get,
    "http_post": script_worker._safe_http_post,
}


def test_example_http_helper_keywords_match_worker_signature():
    examples = sorted(_EXAMPLES_DIR.glob("*.py"))
    # An empty glob or a run without a single helper call would pass vacuously.
    assert examples, f"no hook examples under {_EXAMPLES_DIR}"

    allowed = {name: list(inspect.signature(fn).parameters) for name, fn in _HELPERS.items()}
    calls = 0
    problems = []
    for path in examples:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _HELPERS
            ):
                continue
            calls += 1
            helper = node.func.id
            for kw in node.keywords:
                if kw.arg in allowed[helper]:
                    continue
                arg = kw.arg if kw.arg is not None else f"**{ast.unparse(kw.value)}"
                problems.append(
                    f"{path.relative_to(_ROOT)}:{kw.lineno}: {helper}() has no parameter "
                    f"{arg!r}; allowed: {', '.join(allowed[helper])}"
                )

    assert calls, f"no http_get/http_post call in {_EXAMPLES_DIR}"
    assert not problems, "\n".join(problems)
