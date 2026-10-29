# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""models.py depends inside app only on app.core (R-0696).

The domain modules import the models — builtin_templates, template_sync, the
scheduler behind them. A model that imports one of them back closes a cycle that
only works while the import stays inside a function, and no behavioural test
notices it: both directions still run. An ast scan over every import, nested ones
included, is what keeps it from coming back.
"""

import ast
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent / "app"


def _app_imports(path: Path) -> list[str]:
    modules = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            modules.append(node.module)
        elif isinstance(node, ast.ImportFrom):
            # Relative to a module directly under app/.
            modules.append("app." + (node.module or ""))
    return [m for m in modules if m == "app" or m.startswith("app.")]


def test_models_import_only_app_core():
    imports = _app_imports(_APP / "models.py")
    assert imports, "the scan found no app import in models.py"
    assert [m for m in imports if not m.startswith("app.core.")] == []
