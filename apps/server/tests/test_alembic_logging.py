# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""alembic's env.py must not switch off the app's loggers on its way through (R-0042 T7).

`logging.config.fileConfig` defaults to disable_existing_loggers=True, which sets
`.disabled = True` on every logger that already exists and is not named in alembic.ini —
`adminhelper.*` and `app.core.ssrf` included. Nothing fails loudly when that happens: a log
line simply stops appearing, for the rest of the process.

This copy has passed `disable_existing_loggers=False` since 4060e141 (2026-07-06) and says
why in a comment — but nothing enforced it. The monitoring copy never got the fix, drifted
for two months, and surfaced only as a red CI job on an unrelated guard (R-0042 T6). A
comment is not a guard; this test is, and the monitoring suite carries the same one.
"""

import io
import logging
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parents[1]


def test_an_env_py_run_leaves_existing_loggers_alive():
    from alembic.config import Config
    from alembic.runtime.environment import EnvironmentContext
    from alembic.script import ScriptDirectory

    canary = logging.getLogger("adminhelper.filecfg_canary")
    assert not canary.disabled, "a freshly created logger starts enabled — guard the guard"
    # Cleared so the level check below proves that THIS run configured logging, rather than
    # inheriting an INFO left behind by an earlier test in the same process.
    logging.getLogger("alembic").setLevel(logging.NOTSET)

    cfg = Config(str(_SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_SERVER_DIR / "alembic"))
    ini_url = cfg.get_main_option("sqlalchemy.url")  # the placeholder, until env.py overwrites it
    # Offline mode renders SQL; without a buffer alembic's BEGIN/COMMIT would go to stdout.
    cfg.output_buffer = io.StringIO()
    script = ScriptDirectory.from_config(cfg)

    # Run env.py itself with a plan that applies no migration: its logging setup is what is
    # under test, not the chain. (Rendering the chain would need a database — at least one
    # migration queries the bind while it upgrades.)
    with EnvironmentContext(cfg, script, fn=lambda _rev, _ctx: [], as_sql=True):
        script.run_env()

    assert cfg.get_main_option("sqlalchemy.url") != ini_url, (
        "env.py did not run — it overwrites sqlalchemy.url from the app config, and without "
        "that this test would pass for the wrong reason"
    )
    assert logging.getLogger("alembic").level == logging.INFO, (
        "env.py ran but its fileConfig call did not — only alembic.ini sets this level, and "
        "the canary below would pass vacuously without it"
    )
    assert not canary.disabled, (
        "alembic disabled a pre-existing logger — env.py has to pass "
        "disable_existing_loggers=False to fileConfig (see the comment there)"
    )
