# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""frps.toml in the volume shared with the frps container: written atomically (temp file in the
same directory, fsync, os.replace, 0600), removed best effort, and reconciled with the DB in both
directions when the server starts, which also removes the temp files a killed write left behind."""

import errno
import logging
import os
import stat
import time
from datetime import datetime
from pathlib import Path

import pytest

from app.modules.frp import docker_manager
from app.modules.frp.config_generator import generate_frps_toml
from app.modules.frp.models import FrpServerConfig


@pytest.fixture()
def frp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(docker_manager, "FRP_CONFIG_DIR", tmp_path)
    return tmp_path


def _aged(path: Path, seconds: float) -> Path:
    then = time.time() - seconds
    os.utime(path, (then, then), follow_symlinks=False)
    return path


def _temp_file(directory: Path, name: str, *, age: float) -> Path:
    path = directory / f".frps.toml.{name}.tmp"
    path.write_text("# config of a killed write\n")
    return _aged(path, age)


def _cfg(**fields) -> FrpServerConfig:
    values = {
        "id": "c1",
        "name": "c1",
        "server_addr": "frps.example.net",
        "bind_port": 7000,
        "auth_token": "t" * 32,
    }
    values.update(fields)
    return FrpServerConfig(**values)


def test_a_reader_never_sees_a_half_written_file(frp_dir, monkeypatch):
    # The new content goes to a temp file next to frps.toml, is synced, and only then swapped in.
    # A reader that opened frps.toml before the write keeps the complete old file; truncating and
    # rewriting in place would hand it an empty or partial one.
    old = frp_dir / "frps.toml"
    old.write_text("# previous config\n# old, complete\n")
    config = _cfg(auth_token="n" * 32)
    expected = generate_frps_toml(config)

    events = []
    seen = {}
    real_fsync, real_replace = os.fsync, os.replace

    def spy_fsync(fd):
        events.append("fsync dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync")
        return real_fsync(fd)

    def spy_replace(src, dst):
        events.append("replace")
        src, dst = Path(src), Path(dst)
        seen["src_dir"] = src.parent
        seen["src_text"] = src.read_text()
        seen["src_mode"] = src.stat().st_mode & 0o777
        seen["dst_text"] = dst.read_text()
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)

    with open(old) as reader:
        path = docker_manager.write_frps_config(config)
        assert reader.read() == "# previous config\n# old, complete\n"

    assert path == old
    assert path.read_text() == expected
    # The temp file is synced before the swap, the directory after it: only then is the new
    # directory entry durable.
    assert events == ["fsync", "replace", "fsync dir"]
    assert seen["src_dir"] == frp_dir, "temp file must live in the same directory (same fs)"
    assert seen["src_text"] == expected, "only a complete file is swapped in"
    assert seen["src_mode"] == 0o600, "the temp file holds the token: 0600 before it is visible"
    assert seen["dst_text"] == "# previous config\n# old, complete\n", "target untouched until swap"
    assert sorted(p.name for p in frp_dir.iterdir()) == ["frps.toml"]


def test_a_directory_that_cannot_be_synced_still_keeps_the_new_config(frp_dir, monkeypatch, caplog):
    config = _cfg(auth_token="n" * 32)
    real_fsync = os.fsync

    def no_dir_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "Invalid argument")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", no_dir_fsync)
    with caplog.at_level(logging.WARNING):
        path = docker_manager.write_frps_config(config)
    assert path == frp_dir / "frps.toml"
    assert path.read_text() == generate_frps_toml(config)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "OSError" in warnings[0].getMessage()
    assert warnings[0].exc_info is None


def test_a_failed_swap_keeps_the_old_file_and_leaves_no_temp_file(frp_dir, monkeypatch):
    old = frp_dir / "frps.toml"
    old.write_text("# previous config\n")

    def boom(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        docker_manager.write_frps_config(_cfg())
    assert old.read_text() == "# previous config\n"
    assert sorted(p.name for p in frp_dir.iterdir()) == ["frps.toml"]


@pytest.mark.parametrize("umask", [0o000, 0o277])
def test_the_file_lands_0600_whatever_the_umask(frp_dir, umask):
    stale = frp_dir / "frps.toml"
    stale.write_text("old")
    stale.chmod(0o644)
    previous = os.umask(umask)
    try:
        path = docker_manager.write_frps_config(_cfg())
    finally:
        os.umask(previous)
    assert path.stat().st_mode & 0o777 == 0o600


def test_a_runtime_change_logs_that_frps_applies_it_itself(frp_dir, caplog):
    # frps picks a changed frps.toml up by itself, so a runtime write is an info line, not a
    # warning asking for a manual restart; the startup write says nothing about it.
    with caplog.at_level(logging.INFO, logger=docker_manager.logger.name):
        docker_manager.write_frps_config(_cfg(), warn_restart=True)
    runtime = [r for r in caplog.records if "applies" in r.getMessage()]
    assert runtime and all(r.levelno == logging.INFO for r in runtime)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not any("restart frps" in r.getMessage() for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=docker_manager.logger.name):
        docker_manager.write_frps_config(_cfg())
    assert not any("applies" in r.getMessage() for r in caplog.records)


def test_remove_deletes_the_file(frp_dir):
    (frp_dir / "frps.toml").write_text("# previous config\n")
    docker_manager.remove_frps_config()
    assert not (frp_dir / "frps.toml").exists()


def test_remove_without_a_file_is_a_no_op(frp_dir):
    docker_manager.remove_frps_config()
    assert list(frp_dir.iterdir()) == []


def test_remove_logs_an_oserror_instead_of_raising(frp_dir, caplog):
    # unlink(2) on a directory fails with a real OSError (EISDIR), also as root. The DB is the
    # source of truth: a failed removal is logged, never raised.
    (frp_dir / "frps.toml").mkdir()
    with caplog.at_level(logging.ERROR, logger=docker_manager.logger.name):
        docker_manager.remove_frps_config()
    assert any("frps.toml" in r.getMessage() for r in caplog.records)


def test_a_failed_removal_logs_only_the_error_type(frp_dir, caplog):
    (frp_dir / "frps.toml").mkdir()
    with caplog.at_level(logging.ERROR, logger=docker_manager.logger.name):
        docker_manager.remove_frps_config()
    errors = [
        r
        for r in caplog.records
        if r.name == docker_manager.logger.name and r.levelno == logging.ERROR
    ]
    assert len(errors) == 1
    assert "frps.toml" in errors[0].getMessage()
    assert "IsADirectoryError" in errors[0].getMessage()
    assert all(r.exc_info is None for r in caplog.records)
    assert "Is a directory" not in caplog.text


def test_delete_route_answers_204_when_the_file_cannot_be_removed(
    test_client, db_session, admin_user, frp_dir, monkeypatch
):
    import app.modules.frp.config_router as cr

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    created = test_client.post(
        "/api/frp/server-config",
        json={"name": "test-frps", "server_addr": "frps.example.net"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    (frp_dir / "frps.toml").mkdir()

    deleted = test_client.delete(f"/api/frp/server-config/{created.json()['id']}", headers=h)
    assert deleted.status_code == 204, deleted.text
    assert db_session.query(FrpServerConfig).count() == 0


def test_startup_without_a_db_config_removes_frps_toml(db_session, frp_dir):
    import app.main as m

    (frp_dir / "frps.toml").write_text("# previous config\n")
    m._ensure_frps_config(db_session)
    assert not (frp_dir / "frps.toml").exists()


def test_startup_with_a_db_config_writes_frps_toml(db_session, frp_dir):
    import app.main as m

    config = _cfg(id="cfg-start", name="cfg-start", created_at=datetime(2020, 1, 1))
    db_session.add(config)
    db_session.commit()
    (frp_dir / "frps.toml").write_text("# previous config\n")

    m._ensure_frps_config(db_session)
    path = frp_dir / "frps.toml"
    assert path.read_text() == generate_frps_toml(config)
    assert path.stat().st_mode & 0o777 == 0o600


def _startup_reconcile_log(db, caplog) -> list[logging.LogRecord]:
    import app.main as m

    with caplog.at_level(logging.INFO, logger=m.logger.name):
        m._ensure_frps_config(db)
    return [r for r in caplog.records if r.name == m.logger.name]


def test_a_failed_startup_reconcile_logs_the_error_type_only(
    db_session, frp_dir, monkeypatch, caplog
):
    # A database error quotes the connection, password included: like the startup checks
    # before it, the reconcile logs the type of the error, without its text or a traceback.
    from sqlalchemy.exc import OperationalError

    from app.modules.frp import _helpers

    def unreachable(db, config_id=None):
        raise OperationalError(
            "SELECT 1", {}, Exception("connection failed: password=s3cr3t-pw host=db.example")
        )

    monkeypatch.setattr(_helpers, "get_frp_config", unreachable)
    records = _startup_reconcile_log(db_session, caplog)

    warnings = [r.getMessage() for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "OperationalError" in warnings[0]
    assert "s3cr3t-pw" not in caplog.text
    assert not [r for r in caplog.records if r.exc_info]
    assert "Traceback" not in caplog.text


def test_a_failed_startup_write_logs_the_error_type_only(db_session, frp_dir, monkeypatch, caplog):
    db_session.add(_cfg(id="cfg-start", name="cfg-start", created_at=datetime(2020, 1, 1)))
    db_session.commit()

    def refused(config, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied", "/frp/.frps.toml.x.tmp")

    monkeypatch.setattr(docker_manager, "write_frps_config", refused)
    records = _startup_reconcile_log(db_session, caplog)

    warnings = [r.getMessage() for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "PermissionError" in warnings[0]
    assert "Permission denied" not in caplog.text
    assert not [r for r in caplog.records if r.exc_info]
    assert "Traceback" not in caplog.text


@pytest.mark.parametrize("with_db_config", [False, True])
def test_startup_removes_old_temp_files_and_keeps_fresh_ones(db_session, frp_dir, with_db_config):
    # A SIGKILL or OOM between mkstemp and os.replace leaves the 0600 temp file, with the token of
    # its time, in the volume. Every uvicorn worker runs the startup: a temp file younger than a
    # minute may be the one another worker is writing right now, so it stays.
    import app.main as m

    if with_db_config:
        db_session.add(_cfg(id="cfg-start", name="cfg-start", created_at=datetime(2020, 1, 1)))
        db_session.commit()
    old = _temp_file(frp_dir, "k1lled", age=3600)
    fresh = _temp_file(frp_dir, "wr1ting", age=0)

    m._ensure_frps_config(db_session)

    assert not old.exists()
    assert fresh.exists()
    assert (frp_dir / "frps.toml").exists() is with_db_config


def test_the_cleanup_leaves_frps_toml_other_names_and_symlinks_alone(frp_dir, tmp_path_factory):
    target = tmp_path_factory.mktemp("elsewhere") / "kept"
    target.write_text("# not ours\n")
    _aged(target, 3600)
    link = frp_dir / ".frps.toml.l1nk.tmp"
    link.symlink_to(target)
    kept = [link]
    for name in ("frps.toml", "frps.toml.tmp", ".frps.toml.x.bak"):
        (frp_dir / name).write_text("# keep\n")
        kept.append(_aged(frp_dir / name, 3600))
    _aged(link, 3600)
    old = _temp_file(frp_dir, "k1lled", age=3600)

    assert docker_manager.remove_stale_temp_files() == 1

    assert not old.exists()
    assert all(os.path.lexists(path) for path in kept)
    assert link.is_symlink() and target.read_text() == "# not ours\n"


def test_a_failed_removal_is_logged_and_the_rest_goes_on(db_session, frp_dir, monkeypatch, caplog):
    import app.main as m

    config = _cfg(id="cfg-start", name="cfg-start", created_at=datetime(2020, 1, 1))
    db_session.add(config)
    db_session.commit()
    stuck = _temp_file(frp_dir, "stuck", age=3600)
    gone = _temp_file(frp_dir, "g0ne", age=3600)
    rest = [_temp_file(frp_dir, name, age=3600) for name in ("a1", "b2")]
    real_unlink = os.unlink

    def unlink(path, *args, **kwargs):
        if os.fspath(path) == os.fspath(stuck):
            raise PermissionError(errno.EACCES, "Permission denied", os.fspath(path))
        if os.fspath(path) == os.fspath(gone):
            # Another worker removed it first.
            real_unlink(path, *args, **kwargs)
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", os.fspath(path))
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink)
    with caplog.at_level(logging.INFO, logger=docker_manager.logger.name):
        m._ensure_frps_config(db_session)

    assert stuck.exists()
    assert not gone.exists() and not any(path.exists() for path in rest)
    assert (frp_dir / "frps.toml").read_text() == generate_frps_toml(config)
    records = [r for r in caplog.records if r.name == docker_manager.logger.name]
    warnings = [r.getMessage() for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "PermissionError" in warnings[0]
    assert "Permission denied" not in warnings[0]
    assert "stale frps temp files removed: 2" in [r.getMessage() for r in records]


def test_an_unlistable_directory_is_logged_not_raised(frp_dir, monkeypatch, caplog):
    monkeypatch.setattr(docker_manager, "FRP_CONFIG_DIR", frp_dir / "missing")
    with caplog.at_level(logging.WARNING, logger=docker_manager.logger.name):
        assert docker_manager.remove_stale_temp_files() == 0
    assert any("FileNotFoundError" in r.getMessage() for r in caplog.records)
