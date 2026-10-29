# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Only one uvicorn worker of a start writes the bootstrap token: the one holding the lock."""

import errno
import fcntl
import logging
import os

import pytest

import app.main as m
from app.core.auth import hash_api_key


@pytest.fixture()
def bootstrap_files(tmp_path, monkeypatch):
    token_file = tmp_path / ".bootstrap_token"
    setup_file = tmp_path / ".bootstrap_setup"
    lock_file = tmp_path / ".bootstrap.lock"
    monkeypatch.setattr(m, "BOOTSTRAP_TOKEN_FILE", token_file)
    monkeypatch.setattr(m, "BOOTSTRAP_SETUP_FILE", setup_file)
    # raising=False: before the lock exists the test fails at its assertion, not at the name.
    monkeypatch.setattr(m, "_BOOTSTRAP_LOCK_FILE", lock_file, raising=False)
    monkeypatch.setattr(m, "_bootstrap_lock_fd", None, raising=False)
    yield token_file, setup_file, lock_file
    if getattr(m, "_bootstrap_lock_fd", None) is not None:
        os.close(m._bootstrap_lock_fd)


def _pair_matches(token_file, setup_file) -> str:
    raw = setup_file.read_text(encoding="utf-8")
    assert raw
    assert token_file.read_text(encoding="utf-8") == hash_api_key(raw)
    return raw


def _app_warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.main" and r.levelno == logging.WARNING]


def test_a_worker_without_the_lock_writes_nothing(bootstrap_files, caplog):
    token_file, setup_file, lock_file = bootstrap_files
    token_file.write_text("leader-hash")
    setup_file.write_text("leader-token")
    # Another worker: flock(2) locks belong to the open file description, so a descriptor of
    # our own conflicts with the one _hold_bootstrap_lock opens.
    other = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with caplog.at_level(logging.INFO):
            m._emit_bootstrap_token()
    finally:
        os.close(other)
    assert token_file.read_text() == "leader-hash"
    assert setup_file.read_text() == "leader-token"
    assert _app_warnings(caplog) == []


def test_the_lock_holder_writes_a_matching_pair_on_every_call(bootstrap_files):
    token_file, setup_file, lock_file = bootstrap_files
    other = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(other)

    m._emit_bootstrap_token()
    first = _pair_matches(token_file, setup_file)
    m._emit_bootstrap_token()
    second = _pair_matches(token_file, setup_file)
    assert first != second


def test_a_lock_that_cannot_be_taken_still_writes_the_token(bootstrap_files, monkeypatch, caplog):
    token_file, setup_file, _ = bootstrap_files

    def no_locks(fd, operation):
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(fcntl, "flock", no_locks)
    with caplog.at_level(logging.WARNING):
        m._emit_bootstrap_token()
    _pair_matches(token_file, setup_file)
    assert len([r for r in _app_warnings(caplog) if "OSError" in r.getMessage()]) == 1
    assert "No locks available" not in caplog.text
