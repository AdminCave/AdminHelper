# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""conftest.py imports every model module (R-0205), through app/model_registry.py
(R-0469): Base.metadata knows only the tables of modules that were imported, and
create_all builds only those. A test that needs a table whose module nobody imported
passed in the full run and failed alone. Read with ast, not through the loaded modules:
those depend on which test ran first."""

import ast
from pathlib import Path

TESTS = Path(__file__).parent
MODULES = TESTS.parent / "app" / "modules"
REGISTRY = TESTS.parent / "app" / "model_registry.py"


def _top_level_imports(source: str) -> set[str]:
    # Module level only: an import inside a fixture runs when the fixture does.
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            # `from app import model_registry` imports the submodule app.model_registry.
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_conftest_imports_every_model_module():
    model_modules = sorted(p.parent.name for p in MODULES.glob("*/models.py"))
    # A glob that finds nothing would make the check pass on nothing.
    assert len(model_modules) >= 10, model_modules
    conftest = _top_level_imports((TESTS / "conftest.py").read_text(encoding="utf-8"))
    assert "app.model_registry" in conftest, "tests/conftest.py does not import app.model_registry"
    imported = _top_level_imports(REGISTRY.read_text(encoding="utf-8"))
    missing = [m for m in model_modules if f"app.modules.{m}.models" not in imported]
    assert missing == [], f"app/model_registry.py does not import the models of: {missing}"
