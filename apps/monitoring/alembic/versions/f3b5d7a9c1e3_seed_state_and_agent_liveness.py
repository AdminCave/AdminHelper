# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""builtin_slug on templates, seed-state tombstones, persisted agent liveness

Revision ID: f3b5d7a9c1e3
Revises: d9e1f3a5b7c2
Create Date: 2026-07-19

Foundation for shipped standard templates and restart-safe agent_ping:
``monitor_seed_state`` records which built-in template slugs were seeded once
(tombstone — a user deletion is never undone by re-seeding),
``monitor_templates.builtin_slug`` marks the origin of a seeded template, and
``monitor_agent_liveness`` persists the last agent report so a service restart
no longer looks like agent staleness.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3b5d7a9c1e3"
down_revision: Union[str, Sequence[str], None] = "d9e1f3a5b7c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitor_seed_state",
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column(
            "seeded_at",
            sa.DateTime(),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("slug"),
    )
    op.create_table(
        "monitor_agent_liveness",
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("last_report_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("server_id"),
    )
    op.add_column("monitor_templates", sa.Column("builtin_slug", sa.String(), nullable=True))
    op.create_index(
        op.f("ix_monitor_templates_builtin_slug"),
        "monitor_templates",
        ["builtin_slug"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_monitor_templates_builtin_slug"), table_name="monitor_templates")
    op.drop_column("monitor_templates", "builtin_slug")
    op.drop_table("monitor_agent_liveness")
    op.drop_table("monitor_seed_state")
