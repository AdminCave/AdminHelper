# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""add server_id to api_keys (IDOR: bind agent keys to their server)

Revision ID: c3a7e1f50b2d
Revises: 0494a8f377ef
Create Date: 2026-06-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a7e1f50b2d'
down_revision: Union[str, Sequence[str], None] = '0494a8f377ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('api_keys', sa.Column('server_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_api_keys_server_id'), 'api_keys', ['server_id'], unique=False)
    op.create_foreign_key(
        'fk_api_keys_server_id_servers',
        'api_keys', 'servers',
        ['server_id'], ['id'],
        ondelete='CASCADE',
    )

    # Backfill: bind existing agent keys (name 'agent-{server.name}') to their
    # server so existing agents keep working after the strict endpoint check.
    # Keys that cannot be resolved stay NULL -> the affected agent must be
    # re-provisioned (safe fail-closed behavior).
    conn = op.get_bind()
    servers = conn.execute(sa.text("SELECT id, name FROM servers")).fetchall()
    by_name: dict[str, str] = {}
    for sid, name in servers:
        by_name.setdefault(name, sid)
    rows = conn.execute(
        sa.text("SELECT id, name FROM api_keys WHERE name LIKE 'agent-%' AND server_id IS NULL")
    ).fetchall()
    for kid, kname in rows:
        sid = by_name.get(kname[len("agent-"):])
        if sid is not None:
            conn.execute(
                sa.text("UPDATE api_keys SET server_id = :sid WHERE id = :kid"),
                {"sid": sid, "kid": kid},
            )


def downgrade() -> None:
    op.drop_constraint('fk_api_keys_server_id_servers', 'api_keys', type_='foreignkey')
    op.drop_index(op.f('ix_api_keys_server_id'), table_name='api_keys')
    op.drop_column('api_keys', 'server_id')
