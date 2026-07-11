# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Provision-token cleanup (5.33): the provision_tokens table must not grow without
bound. A token is single-use and short-lived (24h TTL), so once it is consumed
(used_at set) or past its expiry it is dead weight and gets pruned by a periodic
system job — mirroring the enrollment-token cleanup."""

from __future__ import annotations

import datetime
import uuid

from app.modules.provisioning.models import (
    ProvisionToken,
    cleanup_finished_provision_tokens,
)
from app.modules.servers.models import Server


def _server(db) -> None:
    # provision_tokens.server_id is a FK; seed the referenced server (Postgres enforces it).
    db.add(Server(id="srv-1", name="srv1", hostname="srv1.example.test"))
    db.commit()


def _token(*, used: bool = False, expired: bool = False) -> ProvisionToken:
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return ProvisionToken(
        id=str(uuid.uuid4()),
        server_id="srv-1",
        hashed_token=str(uuid.uuid4()),
        expires_at=(now - datetime.timedelta(minutes=5))
        if expired
        else (now + datetime.timedelta(minutes=5)),
        used_at=now if used else None,
    )


def test_cleanup_removes_used_and_expired_keeps_valid(db_session):
    _server(db_session)
    valid = _token()
    used = _token(used=True)
    expired = _token(expired=True)
    db_session.add_all([valid, used, expired])
    db_session.commit()

    removed = cleanup_finished_provision_tokens(db_session)
    assert removed == 2

    remaining = db_session.query(ProvisionToken).all()
    assert [r.id for r in remaining] == [valid.id]


def test_cleanup_noop_when_all_tokens_live(db_session):
    _server(db_session)
    db_session.add_all([_token(), _token()])
    db_session.commit()

    assert cleanup_finished_provision_tokens(db_session) == 0
    assert db_session.query(ProvisionToken).count() == 2
