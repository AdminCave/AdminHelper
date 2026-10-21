# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""No test reaches the app engine unless it is marked app_engine (R-0526).

A session on app.core.database.engine lies outside the rollback of db_session: it sees
none of the test's data and commits what it writes, and with DATABASE_URL unset
(testcontainers) the engine points at the dev default. Code that catches every
exception, as _run_event does, keeps such a test green, so only the teardown can report
it: a nested pytest session with the real conftest, in a fresh interpreter. The probe
needs no database: the app engine points at a socket directory where no server listens,
so an attempt that gets through fails at once and touches nothing.
"""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_SERVER_ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.database import SessionLocal, engine

HERE = Path(__file__).parent


def _select_one():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # as _run_event (app/core/events.py) does
        return type(getattr(exc, "orig", None) or exc).__name__
    finally:
        db.close()


def test_unmarked():
    (HERE / "unmarked").write_text(_select_one())  # the unmarked attempt


@pytest.mark.app_engine
def test_marked():
    (HERE / "marked").write_text(_select_one())


def test_untouched():
    pass


def test_unmarked_uncaught():
    engine.connect()
"""


def _reports(junit_xml: str) -> dict[str, dict[str, str]]:
    # Per test, its failure, error and skipped entries. A test that fails in the call
    # and errors in the teardown gets two testcase elements of the same name.
    reports: dict[str, dict[str, str]] = {}
    for case in ET.fromstring(junit_xml).iter("testcase") if junit_xml else ():
        reports.setdefault(case.get("name"), {}).update(
            (child.tag, f"{child.get('message', '')}\n{child.text or ''}")
            for child in case
            if child.tag in ("failure", "error", "skipped")
        )
    return reports


def test_an_unmarked_test_fails_once_it_reaches_the_app_engine(tmp_path):
    probe = tmp_path / "test_probe.py"
    probe.write_text(_PROBE)
    socket_dir = tmp_path / "nosock"
    socket_dir.mkdir()
    junit = tmp_path / "junit.xml"
    env = {
        **os.environ,
        "DATA_DIR": str(tmp_path / "data"),
        # Placeholders only: the probe's output may carry nothing of them.
        "DATABASE_URL": f"postgresql+psycopg://plchold_user:plchold_pass@/probe?host={socket_dir}",
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
    reports = _reports(junit_xml)

    def seen(name: str) -> tuple[list[str], str | None]:
        outcome = sorted(reports[name]) if name in reports else ["<not run>"]
        marker = tmp_path / name.removeprefix("test_")
        return outcome, marker.read_text() if marker.exists() else None

    # The unmarked attempt raises the gate's own exception and fails in the teardown;
    # the marked one gets through to the missing server; the uncaught one fails twice.
    names = ("test_unmarked", "test_marked", "test_untouched", "test_unmarked_uncaught")
    assert ({name: seen(name) for name in names}, proc.returncode) == (
        {
            "test_unmarked": (["error"], "AppEngineBlocked"),
            "test_marked": ([], "OperationalError"),
            "test_untouched": ([], None),
            "test_unmarked_uncaught": (["error", "failure"], None),
        },
        1,
    ), f"exit {proc.returncode}, nested session:\n{output[-4000:]}"

    message = reports["test_unmarked"]["error"]
    line = _PROBE.splitlines().index(
        '    (HERE / "unmarked").write_text(_select_one())  # the unmarked attempt'
    )
    assert "teardown" in message, message
    assert f"test_probe.py:{line + 1}" in message, message
    assert "db_session" in message and "app_engine" in message, message
    assert "AppEngineBlocked" in reports["test_unmarked_uncaught"]["failure"]
    # Neither the user and password of the URL nor the socket path, in no form a driver
    # error or a traceback might take: pytest prints the arguments of the last frame it
    # shows, and those of the listener are the connect parameters.
    for text in (output, junit_xml):
        assert "plchold" not in text and "nosock" not in text, output[-4000:]


@pytest.mark.app_engine
@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip(),
    reason="needs DATABASE_URL: the app engine connects to it",
)
def test_a_pooled_connection_of_the_app_engine_is_refused_as_well():
    # The probe never gets a connection, so it only meets the do_connect listener; a
    # connection already in the pool is the checkout listener's. Armed by hand here:
    # the teardown of an unmarked test would fail on the attempt this test provokes.
    from app.core import database
    from tests.conftest import _APP_ENGINE_GATE, AppEngineBlocked

    try:
        with database.engine.connect():
            pass
        assert database.engine.pool.checkedin() >= 1
        _APP_ENGINE_GATE.armed = True
        with pytest.raises(AppEngineBlocked) as refused:
            database.engine.connect()
        # pytest prints the arguments of the last frame it shows: the gate's, none of
        # the connection (the probe's check above covers the do_connect path).
        last = refused.traceback.filter(refused)[-1]
        assert [name for name, _ in last.frame.getargs(var=True)] == ["self"]
        assert _APP_ENGINE_GATE.attempts[-1].startswith("tests/test_conftest_app_engine.py:")
    finally:
        _APP_ENGINE_GATE.armed = False
        _APP_ENGINE_GATE.attempts = []
        database.engine.dispose()
