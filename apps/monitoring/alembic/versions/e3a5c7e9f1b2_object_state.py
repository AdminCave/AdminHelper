# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""object state: the damped state of each object a check names

Revision ID: e3a5c7e9f1b2
Revises: d2f4a6c8e0b1
Create Date: 2026-11-19

R-1559 (docs/features/arch-monitoring-neu-p1.md, ADR 0004 §5):

- ``monitor_object_state``: one row per check and object key, written only
  when the object's damped status, reason or presence changes. It starts
  empty; the first result of each check fills it.

The downgrade drops the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3a5c7e9f1b2"
down_revision: Union[str, Sequence[str], None] = "d2f4a6c8e0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitor_object_state",
        sa.Column("check_id", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("since", sa.DateTime(), nullable=False),
        sa.Column("bad_since", sa.DateTime(), nullable=True),
        sa.Column("fail_count", sa.Integer(), nullable=False),
        sa.Column("stable", sa.Boolean(), nullable=False),
        sa.Column("gone_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["check_id"], ["monitor_checks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("check_id", "object_key"),
    )


def downgrade() -> None:
    op.drop_table("monitor_object_state")
