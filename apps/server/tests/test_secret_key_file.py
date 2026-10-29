# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Private files in DATA_DIR: write_private_file creates its file 0600 from the start (no chmod
afterwards, so no window with wider rights and no chmod error to lose), swaps it in atomically and
replaces a symlink at the target name instead of writing through it. _resolve_secret_key writes a
generated .secret_key with it. No database."""

import errno
import os
import pathlib
import stat

import pytest

from app.core import config


@pytest.fixture()
def umask_zero():
    # Under umask 0 a file created with the default mode is 0666: only a mode set at creation
    # keeps it private.
    previous = os.umask(0)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture()
def no_chmod(monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(pathlib.Path, "chmod", refuse)
    monkeypatch.setattr(os, "chmod", refuse)


def _mode(path: pathlib.Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _names(directory: pathlib.Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def test_the_file_is_0600_from_the_start(tmp_path, umask_zero, no_chmod):
    target = tmp_path / ".secret_key"
    config.write_private_file(target, "s3cr3t-key-ä")
    assert _mode(target) == 0o600
    assert target.read_bytes() == "s3cr3t-key-ä".encode("utf-8")
    assert _names(tmp_path) == [".secret_key"], "no temp file may stay behind"


def test_an_existing_file_is_replaced(tmp_path, umask_zero, no_chmod):
    target = tmp_path / ".bootstrap_setup"
    target.write_text("old content")
    assert _mode(target) == 0o666
    config.write_private_file(target, "new content")
    assert target.read_text(encoding="utf-8") == "new content"
    assert _mode(target) == 0o600
    assert _names(tmp_path) == [".bootstrap_setup"]


def test_a_symlink_at_the_target_name_is_replaced_not_written_through(tmp_path, umask_zero):
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim"
    victim.write_text("untouched\n")
    victim_mode = _mode(victim)
    data = tmp_path / "data"
    data.mkdir()
    target = data / ".secret_key"
    target.symlink_to(victim)

    config.write_private_file(target, "s3cr3t-key")

    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == "s3cr3t-key"
    assert _mode(target) == 0o600
    assert victim.read_text() == "untouched\n"
    assert _mode(victim) == victim_mode
    assert _names(data) == [".secret_key"]


def test_a_failed_swap_raises_and_leaves_no_temp_file(tmp_path, monkeypatch):
    target = tmp_path / ".secret_key"
    target.write_text("old content")

    def boom(src, dst):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError) as raised:
        config.write_private_file(target, "new content")
    assert raised.value.errno == errno.ENOSPC
    assert target.read_text() == "old content"
    assert _names(tmp_path) == [".secret_key"]


def _spy_fsync_and_replace(monkeypatch, calls, fail_on_dirs=False):
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        st = os.fstat(fd)
        calls.append(("fsync", stat.S_ISDIR(st.st_mode), st.st_ino))
        if fail_on_dirs and stat.S_ISDIR(st.st_mode):
            raise OSError(errno.EINVAL, "Invalid argument")
        real_fsync(fd)

    def replace(src, dst):
        calls.append(("replace",))
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)


def test_the_directory_is_synced_after_the_swap(tmp_path, monkeypatch):
    calls = []
    _spy_fsync_and_replace(monkeypatch, calls)
    config.write_private_file(tmp_path / "f", "x")
    assert [c[:2] for c in calls] == [("fsync", False), ("replace",), ("fsync", True)]
    assert calls[2][2] == tmp_path.stat().st_ino


def test_a_failed_directory_sync_is_logged_by_type_and_not_raised(tmp_path, monkeypatch, caplog):
    calls = []
    _spy_fsync_and_replace(monkeypatch, calls, fail_on_dirs=True)
    caplog.set_level("WARNING", logger="adminhelper.config")
    config.write_private_file(tmp_path / "f", "x")
    assert (tmp_path / "f").read_text() == "x"
    warnings = [
        r for r in caplog.records if r.name == "adminhelper.config" and r.levelname == "WARNING"
    ]
    assert len(warnings) == 1
    assert "OSError" in warnings[0].getMessage()
    assert "Invalid argument" not in caplog.text
    assert not any(r.exc_info for r in caplog.records)


@pytest.fixture()
def key_env(request, monkeypatch, tmp_path):
    if request.param is None:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", request.param)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "key_env", [None, "change-me-in-production"], ids=["unset", "default"], indirect=True
)
def test_a_generated_key_is_written_0600_without_chmod(key_env, umask_zero, no_chmod):
    key = config._resolve_secret_key()
    key_file = key_env / ".secret_key"
    assert key
    assert _mode(key_file) == 0o600
    assert key_file.read_text(encoding="utf-8") == key
    assert _names(key_env) == [".secret_key"]
    assert config._resolve_secret_key() == key, "the second call reads the stored key"


@pytest.mark.parametrize("key_env", [None], ids=["unset"], indirect=True)
def test_an_existing_key_file_is_read_unchanged(key_env, umask_zero, no_chmod):
    key_file = key_env / ".secret_key"
    key_file.write_text("stored-key\n")
    before = key_file.stat()

    assert config._resolve_secret_key() == "stored-key"
    after = key_file.stat()
    assert key_file.read_text() == "stored-key\n"
    assert (after.st_ino, after.st_mtime_ns, after.st_mode) == (
        before.st_ino,
        before.st_mtime_ns,
        before.st_mode,
    )
