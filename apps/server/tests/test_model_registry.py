# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Both server processes load every ORM model before their first query (R-0411), and so
do the management CLI and alembic's env.py (R-0469).

Relationships name their targets as strings, which SQLAlchemy resolves when the first
query configures the mappers; a model no import reached is unknown then, and that query
fails. The scheduler process imports only what its jobs need, so every job with a
database access failed ('Connection' has no attribute 'server_id') and APScheduler only
logged it. The test session imports every model itself (conftest), so only a fresh
interpreter shows what a process really loads.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[1]
_MODULES = _SERVER_ROOT / "app" / "modules"

# Nothing in these probes may reach a database; a stray connection is refused at once.
_NO_DATABASE = "postgresql+psycopg://probe@127.0.0.1:1/none"

# Runs scheduler_main.main() up to the point where the scheduler starts its jobs, imports
# what the job bodies import on their first run (argv), and configures the mappers the
# way the first query of a job does. The schema gate and the initial hook reconcile are
# stubbed: both query the database.
_SCHEDULER_PROBE = """
import importlib
import sys

from sqlalchemy.orm import configure_mappers

from app import scheduler_main
from app.modules.hooks import scheduler as jobs


class Started(Exception):
    pass


def start():
    raise Started


scheduler_main._wait_for_schema_head = lambda **_: None
jobs.reconcile_scheduled_hooks = lambda: None
jobs.scheduler.start = start
try:
    scheduler_main.main()
except Started:
    pass
for name in sys.argv[1:]:
    importlib.import_module(name)
configure_mappers()
"""

_REGISTRY_PROBE = """
import sys

import app.model_registry  # noqa: F401

print("\\n".join(name for name in sys.argv[1:] if name not in sys.modules))
"""

_CLI_PROBE = """
import sys

import app.cli  # noqa: F401

print("\\n".join(name for name in sys.argv[1:] if name not in sys.modules))
"""


def _run(code: str, args: list[str], data_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATA_DIR": str(data_dir), "DATABASE_URL": _NO_DATABASE}
    return subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=_SERVER_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _job_imports() -> list[str]:
    """The app modules the scheduler's jobs import inside their bodies."""
    tree = ast.parse((_MODULES / "hooks" / "scheduler.py").read_text())
    return sorted(
        {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.")
        }
    )


def _defines_mapper(models: Path) -> bool:
    tree = ast.parse(models.read_text())
    return any(
        isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "Base" for base in node.bases)
        for node in tree.body
    )


def _models_modules() -> list[str]:
    """Every app.modules.<m>.models that defines a mapper class."""
    return sorted(
        f"app.modules.{models.parent.name}.models"
        for models in _MODULES.glob("*/models.py")
        if _defines_mapper(models)
    )


def _imports_the_registry(node: ast.stmt) -> bool:
    if isinstance(node, ast.ImportFrom):
        return node.module == "app" and any(a.name == "model_registry" for a in node.names)
    if isinstance(node, ast.Import):
        return any(a.name == "app.model_registry" for a in node.names)
    return False


def test_the_scheduler_process_configures_every_mapper(tmp_path):
    imports = _job_imports()
    assert imports, "no job imports found in app/modules/hooks/scheduler.py"
    proc = _run(_SCHEDULER_PROBE, imports, tmp_path)
    assert proc.returncode == 0, proc.stderr[-4000:]


def test_the_registry_imports_every_models_module(tmp_path):
    expected = _models_modules()
    assert expected, f"no models.py with a mapper under {_MODULES}"
    proc = _run(_REGISTRY_PROBE, expected, tmp_path)
    assert proc.returncode == 0, proc.stderr[-4000:]
    assert proc.stdout.split() == []


def test_the_cli_imports_every_models_module(tmp_path):
    # `python -m app.cli` is a process of its own (install.sh bootstraps the first admin and
    # its enrollment token with it), so it needs the same models as the other entry points.
    expected = _models_modules()
    assert expected, f"no models.py with a mapper under {_MODULES}"
    proc = _run(_CLI_PROBE, expected, tmp_path)
    assert proc.returncode == 0, proc.stderr[-4000:]
    assert proc.stdout.split() == []


def test_alembic_env_imports_the_registry_at_module_level():
    # Read, not imported: importing env.py runs the migrations. target_metadata knows only the
    # tables of the models loaded by then; autogenerate and `alembic check` would take every
    # other table for one to drop (R-0469).
    tree = ast.parse((_SERVER_ROOT / "alembic" / "env.py").read_text())
    assert any(_imports_the_registry(node) for node in tree.body), (
        "alembic/env.py does not import app.model_registry at module level"
    )
