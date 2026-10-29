# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A test whose database connection fails leaves the password of DATABASE_URL out of
the terminal and the JUnit report, also with -l (R-0591)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SERVER_ROOT = Path(__file__).resolve().parent.parent

_PROBE = "def test_needs_db(db_session):\n    pass\n"


@pytest.mark.parametrize("extra", [[], ["-l"]], ids=["plain", "showlocals"])
def test_the_database_password_stays_out_of_the_report(tmp_path, extra):
    probe = tmp_path / "test_probe.py"
    probe.write_text(_PROBE)
    socket_dir = tmp_path / "nosock"
    socket_dir.mkdir()
    junit = tmp_path / "junit.xml"
    env = {
        **os.environ,
        "DATA_DIR": str(tmp_path / "data"),
        # Placeholders only. %40 is '@': the decoded and the raw form differ.
        "DATABASE_URL": f"postgresql+psycopg://plchold_user:plchold_pw%40591@/probe?host={socket_dir}",
    }
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "tests.conftest",
                "-p",
                "no:cacheprovider",
                "-q",
                f"--junitxml={junit}",
                *extra,
                str(probe),
            ],
            cwd=_SERVER_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        # No traceback: the frames of subprocess.run carry env.
        pytest.fail("the nested session did not end within 120 s", pytrace=False)
    output = proc.stdout + proc.stderr
    junit_xml = junit.read_text() if junit.exists() else ""
    for text in (output, junit_xml):
        assert "plchold_pw" not in text, "the password stood in the report"
    # The counter-check: the run reached the failed connection, and the mask took effect.
    assert "OperationalError" in output, output[-3000:].replace("plchold_pw", "<pw>")
    assert "***" in output, output[-3000:].replace("plchold_pw", "<pw>")
