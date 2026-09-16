# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""alembic's env.py must not switch off the app's loggers on its way through (R-0042 T6).

`logging.config.fileConfig` defaults to disable_existing_loggers=True, which sets
`.disabled = True` on every logger that already exists and is not named in alembic.ini —
`monitor.*` and `app.core.ssrf` included. Nothing fails loudly when that happens: a log
line simply stops appearing, for the rest of the process. It cost a red CI run on the SSRF
guard's cap warning, and the server copy had carried the fix (and the explanation) since
2026-07-06 while this one had not.

Offline mode (`sql=True`) renders the migrations instead of applying them: it needs no
database, so this runs in the ordinary fast suite rather than only where a Postgres
happens to be — the drift lived two months precisely because the check was DB-gated.
It still goes through the same fileConfig line, which is the whole point.
"""

import io
import logging
from pathlib import Path

_MONITORING_DIR = Path(__file__).resolve().parents[1]


def test_a_migration_run_leaves_existing_loggers_alive():
    from alembic import command
    from alembic.config import Config

    canary = logging.getLogger("monitor.filecfg_canary")
    assert not canary.disabled, "a freshly created logger starts enabled — guard the guard"

    cfg = Config(str(_MONITORING_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_MONITORING_DIR / "alembic"))
    # Where alembic puts the rendered SQL in offline mode; without it, every migration in
    # the chain would be printed into the test output.
    cfg.output_buffer = io.StringIO()

    command.upgrade(cfg, "head", sql=True)

    assert "CREATE TABLE" in cfg.output_buffer.getvalue(), (
        "offline upgrade rendered no schema — env.py did not actually run, so this test "
        "would pass for the wrong reason"
    )
    assert not canary.disabled, (
        "alembic disabled a pre-existing logger — env.py has to pass "
        "disable_existing_loggers=False to fileConfig, the way the server copy does"
    )
