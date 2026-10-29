# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Module boundaries inside app (R-0696).

(a) models.py depends inside app only on app.core.

The domain modules import the models — builtin_templates, template_sync, the
scheduler behind them. A model that imports one of them back closes a cycle that
only works while the import stays inside a function, and no behavioural test
notices it: both directions still run. An ast scan over every import, nested ones
included, is what keeps it from coming back.

(b) No module takes a private name from another one, neither imported nor read
through an imported module. Tests stay outside: they may patch private names.
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


def _module_name(path: Path) -> str:
    parts = path.relative_to(_APP.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _is_app_module(dotted: str) -> bool:
    path = _APP.parent.joinpath(*dotted.split("."))
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def _private_crossings(path: Path) -> tuple[list[str], int]:
    """Private names this module takes from another app module, and how many
    app imports it has."""
    me = _module_name(path)
    where = path.relative_to(_APP.parent)
    package = me if path.name == "__init__.py" else me.rpartition(".")[0]
    found, app_imports, module_aliases = [], 0, {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    app_imports += 1
                    if alias.asname:
                        module_aliases[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                source = f"{base}.{node.module}" if node.module else base
            else:
                source = node.module or ""
            if source != "app" and not source.startswith("app."):
                continue
            app_imports += 1
            for alias in node.names:
                if _is_app_module(f"{source}.{alias.name}"):
                    module_aliases[alias.asname or alias.name] = f"{source}.{alias.name}"
                elif source != me and _is_private(alias.name):
                    found.append(f"{where}:{node.lineno} imports {alias.name} from {source}")
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and module_aliases.get(node.value.id, me) != me
            and _is_private(node.attr)
        ):
            found.append(f"{where}:{node.lineno} reads {node.value.id}.{node.attr}")
    return found, app_imports


def test_no_private_name_crosses_a_module_boundary():
    modules = sorted(p for p in _APP.rglob("*.py") if "__pycache__" not in p.parts)
    crossings, app_imports = [], 0
    for path in modules:
        found, count = _private_crossings(path)
        crossings += found
        app_imports += count
    assert len(modules) >= 30, f"the scan read only {len(modules)} modules"
    assert app_imports >= 50, f"the scan found only {app_imports} app imports"
    assert crossings == []
