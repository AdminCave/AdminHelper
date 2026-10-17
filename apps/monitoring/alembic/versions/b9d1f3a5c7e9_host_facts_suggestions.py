# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""host facts and ignored template suggestions

Revision ID: b9d1f3a5c7e9
Revises: a7c9e1b3d5f7
Create Date: 2026-10-17

R-0421 (docs/features/monitoring-discovery.md): ``monitor_host_facts`` keeps the
``host`` block of the last agent report per server (OS, platform, virtualization,
detected subsystems as a JSON list), from which the service suggests standard
templates. ``monitor_template_suggestion_dismissals`` records a suggestion an
admin ignored, per (server, built-in slug), so it is not suggested again.
Metadata only: the downgrade drops both tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9d1f3a5c7e9"
down_revision: Union[str, Sequence[str], None] = "a7c9e1b3d5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitor_host_facts",
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("os", sa.String(), nullable=True),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("platform_version", sa.String(), nullable=True),
        sa.Column("virt_system", sa.String(), nullable=True),
        sa.Column("virt_role", sa.String(), nullable=True),
        sa.Column("subsystems", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("server_id"),
    )
    op.create_table(
        "monitor_template_suggestion_dismissals",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("builtin_slug", sa.String(), nullable=False),
        sa.Column(
            "dismissed_at",
            sa.DateTime(),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_id", "builtin_slug", name="uq_suggestion_dismissal_server_slug"
        ),
    )
    op.create_index(
        op.f("ix_monitor_template_suggestion_dismissals_server_id"),
        "monitor_template_suggestion_dismissals",
        ["server_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_monitor_template_suggestion_dismissals_server_id"),
        table_name="monitor_template_suggestion_dismissals",
    )
    op.drop_table("monitor_template_suggestion_dismissals")
    op.drop_table("monitor_host_facts")
