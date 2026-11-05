# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""add connection_sessions

Revision ID: c8e2f4a6b0d1
Revises: a7c3e9d1f5b2
Create Date: 2026-11-05

The session history of a connection (R-1068). A table of its own rather than the audit log:
the audit log knows no end of a session and has a retention of its own.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e2f4a6b0d1"
down_revision: Union[str, Sequence[str], None] = "a7c3e9d1f5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connection_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("connection_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("device", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_connection_sessions_connection_id"),
        "connection_sessions",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connection_sessions_started_at"),
        "connection_sessions",
        ["started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_connection_sessions_started_at"), table_name="connection_sessions")
    op.drop_index(op.f("ix_connection_sessions_connection_id"), table_name="connection_sessions")
    op.drop_table("connection_sessions")
