# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FRP server-config resolution (1.30): get_frp_config resolves the singleton
deterministically (oldest first, id tiebreaker) instead of a non-deterministic
.first(), so the agent sync / startup frps.toml never picks a random row."""

from datetime import datetime

from app.modules.frp._helpers import get_frp_config
from app.modules.frp.models import FrpServerConfig


def _cfg(db, cid: str, created: datetime) -> None:
    db.add(
        FrpServerConfig(
            id=cid,
            name=cid,
            server_addr="frps.example.net",
            bind_port=7000,
            auth_token="tok",
            created_at=created,
        )
    )
    db.commit()


def test_get_frp_config_returns_oldest(db_session):
    # Insert the newer row first: a bare .first() could return either.
    _cfg(db_session, "cfg-new", datetime(2024, 1, 1))
    _cfg(db_session, "cfg-old", datetime(2020, 1, 1))
    assert get_frp_config(db_session).id == "cfg-old"


def test_get_frp_config_by_id(db_session):
    _cfg(db_session, "cfg-a", datetime(2020, 1, 1))
    _cfg(db_session, "cfg-b", datetime(2021, 1, 1))
    assert get_frp_config(db_session, "cfg-b").id == "cfg-b"
    assert get_frp_config(db_session, "does-not-exist") is None


def test_get_frp_config_none_when_empty(db_session):
    assert get_frp_config(db_session) is None


def _create_config(db, monkeypatch, **fields):
    from types import SimpleNamespace

    import app.modules.frp.config_router as cr
    from app.modules.frp.schemas import FrpServerConfigCreate

    monkeypatch.setattr(cr, "write_frps_config", lambda config: None)
    monkeypatch.setattr(cr, "fire_event", lambda *a, **k: None)
    data = FrpServerConfigCreate(name="n", server_addr="a.example", **fields)
    cr.create_server_config(data=data, request=SimpleNamespace(state=SimpleNamespace()), db=db)
    return db.query(FrpServerConfig).one()


def test_create_auto_generates_dashboard_password(db_session, monkeypatch):
    # 3.35: dashboard enabled but no password supplied -> generate a strong one,
    # never leave the frps web UI unauthenticated (an empty password emits no
    # webServer.password line at all).
    cfg = _create_config(db_session, monkeypatch, dashboard_port=7500, dashboard_user="admin")
    assert cfg.dashboard_password and len(cfg.dashboard_password) >= 16


def test_create_without_dashboard_leaves_password_none(db_session, monkeypatch):
    # No dashboard -> no password fabricated.
    cfg = _create_config(db_session, monkeypatch)
    assert cfg.dashboard_password is None


def _update_config(db, monkeypatch, config_id, **fields):
    from types import SimpleNamespace

    import app.modules.frp.config_router as cr
    from app.modules.frp.schemas import FrpServerConfigUpdate

    monkeypatch.setattr(cr, "write_frps_config", lambda config: None)
    monkeypatch.setattr(cr, "fire_event", lambda *a, **k: None)
    data = FrpServerConfigUpdate(**fields)
    cr.update_server_config(
        config_id=config_id, data=data, request=SimpleNamespace(state=SimpleNamespace()), db=db
    )
    return db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).one()


def test_update_enabling_dashboard_auto_generates_password(db_session, monkeypatch):
    # 3.35 (update path): enabling the dashboard on a config that had none must
    # generate a password, not leave the frps web UI unauthenticated.
    cfg = _create_config(db_session, monkeypatch)  # no dashboard
    assert cfg.dashboard_password is None
    updated = _update_config(db_session, monkeypatch, cfg.id, dashboard_port=7500)
    assert updated.dashboard_password and len(updated.dashboard_password) >= 16


def test_update_blanking_dashboard_password_regenerates(db_session, monkeypatch):
    # 3.35 (update path): PUT dashboard_password="" on a dashboard-enabled config
    # must regenerate it, not blank it (empty -> no webServer.password line -> open UI).
    cfg = _create_config(db_session, monkeypatch, dashboard_port=7500)
    updated = _update_config(db_session, monkeypatch, cfg.id, dashboard_password="")
    assert updated.dashboard_password and len(updated.dashboard_password) >= 16
