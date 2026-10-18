# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""frps.toml in the volume shared with the frps container: written atomically (temp file in the
same directory, fsync, os.replace, 0600), removed best effort, and reconciled with the DB in both
directions when the server starts."""

import logging
import os
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
        events.append("fsync")
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
    assert events == ["fsync", "replace"], "the temp file must be synced before the swap"
    assert seen["src_dir"] == frp_dir, "temp file must live in the same directory (same fs)"
    assert seen["src_text"] == expected, "only a complete file is swapped in"
    assert seen["src_mode"] == 0o600, "the temp file holds the token: 0600 before it is visible"
    assert seen["dst_text"] == "# previous config\n# old, complete\n", "target untouched until swap"
    assert sorted(p.name for p in frp_dir.iterdir()) == ["frps.toml"]


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
