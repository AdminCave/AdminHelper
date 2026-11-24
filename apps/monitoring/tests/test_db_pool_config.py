# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The monitoring engine takes its pool from DB_POOL_SIZE/DB_MAX_OVERFLOW, as the
server's does. The engine is built at import, so a fresh interpreter reads the env."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SERVICE = Path(__file__).resolve().parents[1]
_PROBE = (
    "from app.core.database import engine; print(engine.pool.size(), engine.pool._max_overflow)"
)


def _pool(extra: dict[str, str]) -> str:
    env = {k: v for k, v in os.environ.items() if k not in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW")}
    # create_engine does not connect; the address only has to parse.
    env["DATABASE_URL"] = "postgresql+psycopg://probe:probe@192.0.2.1:5432/probe"
    env.update(extra)
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_SERVICE,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip().splitlines()[-1]


def test_pool_defaults_to_10_and_20():
    assert _pool({}) == "10 20"


@pytest.mark.parametrize(("size", "overflow"), [("3", "4")])
def test_pool_from_env(size, overflow):
    assert _pool({"DB_POOL_SIZE": size, "DB_MAX_OVERFLOW": overflow}) == f"{size} {overflow}"
