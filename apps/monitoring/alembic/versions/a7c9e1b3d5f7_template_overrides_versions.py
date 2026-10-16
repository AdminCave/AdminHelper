# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""template overrides, check tombstones, built-in template version

Revision ID: a7c9e1b3d5f7
Revises: c1d3e5f7a9b1
Create Date: 2026-10-16

R-0420 (docs/features/monitoring-templates.md): ``monitor_checks.overridden_fields``
lists the fields a user changed on a template check, so the template sync keeps
them; existing checks start with ``[]`` (nothing counts as changed before this
revision). ``monitor_check_tombstones`` records a deleted template check per
(template, server, def_id) so the sync does not create it again.
``monitor_templates.builtin_version``/``builtin_hash`` record which shipped
version of a standard template was last rolled out. Metadata only: the
downgrade drops it all and the old sync behaviour returns.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c9e1b3d5f7"
down_revision: Union[str, Sequence[str], None] = "c1d3e5f7a9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "monitor_checks",
        sa.Column("overridden_fields", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column("monitor_templates", sa.Column("builtin_version", sa.Integer(), nullable=True))
    op.add_column("monitor_templates", sa.Column("builtin_hash", sa.String(), nullable=True))
    op.create_table(
        "monitor_check_tombstones",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("template_id", sa.String(), nullable=False),
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("def_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["template_id"], ["monitor_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id", "server_id", "def_id", name="uq_check_tombstone_template_server_def"
        ),
    )
    op.create_index(
        op.f("ix_monitor_check_tombstones_server_id"),
        "monitor_check_tombstones",
        ["server_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_monitor_check_tombstones_server_id"), table_name="monitor_check_tombstones"
    )
    op.drop_table("monitor_check_tombstones")
    op.drop_column("monitor_templates", "builtin_hash")
    op.drop_column("monitor_templates", "builtin_version")
    op.drop_column("monitor_checks", "overridden_fields")
