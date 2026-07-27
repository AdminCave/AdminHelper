# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""template→tag assignments and the source marker on server assignments

Revision ID: a5c7e9b1d3f5
Revises: f3b5d7a9c1e3
Create Date: 2026-07-19

Tag-based template assignment (M2): ``monitor_template_tag_assignments`` binds
a template to a server tag; tag_sync materializes per-server assignments from
it. ``monitor_template_assignments.source`` ('manual'|'tag') marks who owns a
row — the sync only creates/removes its own 'tag' rows, existing rows backfill
as 'manual'.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5c7e9b1d3f5"
down_revision: Union[str, Sequence[str], None] = "f3b5d7a9c1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitor_template_tag_assignments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("template_id", sa.String(), nullable=False),
        sa.Column("tag", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["monitor_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "tag", name="uq_tag_assignment_template_tag"),
    )
    op.create_index(
        op.f("ix_monitor_template_tag_assignments_template_id"),
        "monitor_template_tag_assignments",
        ["template_id"],
    )
    op.create_index(
        op.f("ix_monitor_template_tag_assignments_tag"),
        "monitor_template_tag_assignments",
        ["tag"],
    )
    op.add_column(
        "monitor_template_assignments",
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
    )


def downgrade() -> None:
    op.drop_column("monitor_template_assignments", "source")
    op.drop_index(
        op.f("ix_monitor_template_tag_assignments_tag"),
        table_name="monitor_template_tag_assignments",
    )
    op.drop_index(
        op.f("ix_monitor_template_tag_assignments_template_id"),
        table_name="monitor_template_tag_assignments",
    )
    op.drop_table("monitor_template_tag_assignments")
