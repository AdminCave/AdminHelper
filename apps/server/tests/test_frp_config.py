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
