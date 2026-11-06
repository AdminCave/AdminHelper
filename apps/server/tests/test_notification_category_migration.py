# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revision c1a7e3f5b9d2 splits the category lifecycle into tunnel, security and agent
(R-1079): stored bell rows move by their event_type, subscriptions that filter on
lifecycle get the three new names, and the downgrade maps back.

Same pattern as test_outbox_expiry_migration.py: a throwaway database on the session's
Postgres, migrated up to the revision before, seeded, then upgraded.
"""

import json
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

import app.core.config as app_config
from app.modules.notifications.models import Notification

SERVER_DIR = Path(__file__).resolve().parents[1]
REVISION = "c1a7e3f5b9d2"
PREVIOUS = "b4d6f8a0c2e1"

# id: (event_type, category before) -> category after the upgrade
ROWS = {
    1: ("lifecycle.frp.server.applied", "lifecycle", "tunnel"),
    2: ("lifecycle.frp.config.field_rejected", "lifecycle", "tunnel"),
    3: ("lifecycle.frp.tunnel.created", "lifecycle", "tunnel"),
    4: ("lifecycle.certificate.expiry.warning", "lifecycle", "security"),
    5: ("lifecycle.server.deleted", "lifecycle", "agent"),
    6: ("monitoring.check.transition", "monitoring", "monitoring"),
    7: ("security.admin.created", "security", "security"),
}
# id: stored categories before -> after the upgrade
SUBSCRIPTIONS = {
    1: ('["lifecycle"]', ["tunnel", "security", "agent"]),
    2: ('["monitoring", "lifecycle", "security"]', ["monitoring", "tunnel", "security", "agent"]),
    3: ('["monitoring"]', '["monitoring"]'),
    4: (None, None),
    5: ("not json", "not json"),
    6: ('{"lifecycle": true}', '{"lifecycle": true}'),
}


@pytest.fixture()
def before_split(pg_engine, monkeypatch):
    admin_url = pg_engine.url
    dbname = f"alembic_categories_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    url = admin_url.set(database=dbname).render_as_string(hide_password=False)
    # env.py reads app.core.config.DATABASE_URL at execution time — patch the attribute.
    monkeypatch.setattr(app_config, "DATABASE_URL", url)
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    engine = create_engine(url)
    try:
        command.upgrade(cfg, PREVIOUS)
        _seed(engine)
        yield cfg, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin_engine.dispose()


def _seed(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, hashed_password, is_admin)"
                " VALUES (1, 'alice', 'x', true)"
            )
        )
        for nid, (event_type, category, _) in ROWS.items():
            conn.execute(
                text(
                    "INSERT INTO notification (id, user_id, severity, category, event_type, title)"
                    " VALUES (:id, 1, 'warning', :category, :event_type, 'notice')"
                ),
                {"id": nid, "category": category, "event_type": event_type},
            )
        for sid, (categories, _) in SUBSCRIPTIONS.items():
            conn.execute(
                text(
                    "INSERT INTO notification_subscription (id, user_id, scope_type,"
                    " min_severity, categories, channel_email, channel_telegram, enabled)"
                    " VALUES (:id, 1, 'all', 'info', :categories, false, false, true)"
                ),
                {"id": sid, "categories": categories},
            )


def _categories(engine) -> dict[int, str]:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, category FROM notification ORDER BY id")).all())


def _subscriptions(engine) -> dict[int, str | None]:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text("SELECT id, categories FROM notification_subscription ORDER BY id")
            ).all()
        )


def _as_stored(raw: str | None, expected):
    # A rewritten filter is compared as a list; one left alone byte for byte.
    if isinstance(expected, list):
        return json.loads(raw)
    return raw


def test_upgrade_moves_rows_by_event_type_and_widens_lifecycle_filters(before_split):
    cfg, engine = before_split

    command.upgrade(cfg, REVISION)

    assert _categories(engine) == {nid: after for nid, (_, _, after) in ROWS.items()}
    stored = _subscriptions(engine)
    assert {sid: _as_stored(stored[sid], after) for sid, (_, after) in SUBSCRIPTIONS.items()} == {
        sid: after for sid, (_, after) in SUBSCRIPTIONS.items()
    }


def test_downgrade_maps_tunnel_and_agent_back_to_lifecycle(before_split):
    cfg, engine = before_split
    command.upgrade(cfg, REVISION)
    with engine.begin() as conn:
        # A filter picked after the upgrade: only tunnel. The downgrade cannot keep it
        # that narrow (documented in the revision).
        conn.execute(
            text(
                "INSERT INTO notification_subscription (id, user_id, scope_type, min_severity,"
                " categories, channel_email, channel_telegram, enabled)"
                " VALUES (7, 1, 'all', 'info', '[\"tunnel\"]', false, false, true)"
            )
        )

    command.downgrade(cfg, PREVIOUS)

    assert _categories(engine) == {nid: before for nid, (_, before, _) in ROWS.items()}
    stored = _subscriptions(engine)
    assert json.loads(stored[1]) == ["lifecycle", "security"]
    assert json.loads(stored[2]) == ["monitoring", "lifecycle", "security"]
    assert json.loads(stored[7]) == ["lifecycle"]
    for sid in (3, 4, 5, 6):
        assert stored[sid] == SUBSCRIPTIONS[sid][0], f"subscription {sid} changed"


def test_frp_config_notices_of_the_server_are_tunnel(db_session, admin_user):
    """The startup notices of main (frp_config) write the category the upgrade gives
    their old rows; the other producers are covered in their own tests."""
    import app.main as m

    m._tell_admins(db_session, "lifecycle.frp.config.field_rejected", "t", "b", "frps-1")

    rows = db_session.query(Notification).filter(Notification.source_type == "frp_config").all()
    assert [(r.user_id, r.category) for r in rows] == [(admin_user.id, "tunnel")]
