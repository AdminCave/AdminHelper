# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""maintenance windows (collect-but-mute)

Revision ID: b7d9f1a3c5e7
Revises: a5c7e9b1d3f5
Create Date: 2026-07-19

M3: ``monitor_maintenance`` — one-off windows as naive-UTC timestamps, weekly
windows as weekday/start_time/duration evaluated in an IANA timezone
(DST-correct via zoneinfo). server_id NULL = all servers.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d9f1a3c5e7"
down_revision: Union[str, Sequence[str], None] = "a5c7e9b1d3f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitor_maintenance",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("server_id", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("weekdays", sa.String(), nullable=True),
        sa.Column("start_time", sa.String(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(), server_default="UTC", nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_monitor_maintenance_server_id"), "monitor_maintenance", ["server_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_monitor_maintenance_server_id"), table_name="monitor_maintenance")
    op.drop_table("monitor_maintenance")
