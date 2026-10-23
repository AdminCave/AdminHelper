# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""MTLS_ENFORCE is read the same way by the server and the gateway.

One variable drives both (docs: Betrieb, mTLS scharfschalten). The gateway reads it in a
``case`` block of its entrypoint, the server with ``parse_mtls_enforce``. A value the two
read differently leaves the gateway enforcing at the handshake while the server only logs
scope mismatches per route. The table pins the server, the parity test runs the gateway's
own ``case`` block for every value of the table and compares."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import parse_mtls_enforce

_ROOT = Path(__file__).resolve().parents[3]
_SERVER_ROOT = Path(__file__).resolve().parents[1]
_ENTRYPOINT = _ROOT / "apps" / "gateway" / "docker-entrypoint.sh"

ENFORCING = ["true", "TRUE", "1", "yes", "on", "On"]
PERMISSIVE = ["false", "0", "no", "off", "OFF"]
DEFAULT = [None, ""]
# Neither trimmed nor guessed: the gateway does not strip blanks either.
UNKNOWN = ["ture", "enforced", " true"]
ALL_VALUES = ENFORCING + PERMISSIVE + DEFAULT + UNKNOWN


def _warnings(caplog) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records if r.name == "adminhelper.config" and r.levelno == logging.WARNING
    ]


# --- the server's table ------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [(v, True) for v in ENFORCING + DEFAULT] + [(v, False) for v in PERMISSIVE],
)
def test_known_values_without_a_warning(value, expected, caplog):
    with caplog.at_level(logging.WARNING, logger="adminhelper.config"):
        assert parse_mtls_enforce(value) is expected
    assert _warnings(caplog) == []


@pytest.mark.parametrize("value", UNKNOWN)
def test_unknown_value_enforces_with_one_warning(value, caplog):
    with caplog.at_level(logging.WARNING, logger="adminhelper.config"):
        assert parse_mtls_enforce(value) is True
    records = _warnings(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert repr(value) in message
    assert "fail-closed" in message


@pytest.mark.parametrize("value, expected", [("on", "True"), ("ture", "True"), ("off", "False")])
def test_config_reads_the_env_through_the_parser(value, expected, tmp_path):
    # config reads the environment once at import, and conftest sets MTLS_ENFORCE=false
    # for the suite: only a fresh interpreter sees what config makes of the variable.
    env = {k: v for k, v in os.environ.items() if k != "MTLS_ENFORCE"}
    env["DATA_DIR"] = str(tmp_path)
    env["MTLS_ENFORCE"] = value
    proc = subprocess.run(
        [sys.executable, "-c", "from app.core import config; print(config.MTLS_ENFORCE)"],
        cwd=_SERVER_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == expected


# --- parity with the gateway entrypoint --------------------------------------


def _gateway_case_block() -> str:
    # The same range as scripts/tests/gateway_mtls_test.sh (awk '/^case .*MTLS_ENFORCE/,/^esac/').
    match = re.search(
        r"^case [^\n]*MTLS_ENFORCE.*?^esac[^\n]*$",
        _ENTRYPOINT.read_text(),
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"no MTLS_ENFORCE case block in {_ENTRYPOINT}"
    return match.group(0)


def _gateway_enforces(value: str | None, snippet_dir: Path) -> bool:
    snippet_dir.mkdir()
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "SNIPPET_DIR": str(snippet_dir)}
    if value is not None:
        env["MTLS_ENFORCE"] = value
    proc = subprocess.run(
        ["sh", "-c", _gateway_case_block()],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    snippet = (snippet_dir / "data-plane-mtls.conf").read_text().strip()
    assert snippet in ("ssl_verify_client on;", "ssl_verify_client optional;"), snippet
    return snippet == "ssl_verify_client on;"


@pytest.mark.parametrize("value", ALL_VALUES)
def test_server_and_gateway_read_the_same(value, tmp_path):
    assert parse_mtls_enforce(value) is _gateway_enforces(value, tmp_path / "snippets")
