# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""notify_mail_template: the mail template of the panel

Revision ID: d7b2e4c6a8f0
Revises: c4e8a1f2b3d5
Create Date: 2026-11-18

One row (id 1) an admin fills in the web panel (R-1533). The upgrade writes no row, so
the mails stay plain text with the bare title as subject until an admin sets a
template. The downgrade drops the table and with it the template and the logo.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7b2e4c6a8f0"
down_revision: Union[str, Sequence[str], None] = "c4e8a1f2b3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notify_mail_template",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_prefix", sa.String(length=100), nullable=True),
        sa.Column("from_name", sa.String(length=100), nullable=True),
        sa.Column("html", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("logo", sa.LargeBinary(), nullable=True),
        sa.Column("logo_type", sa.String(length=20), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_notify_mail_template_single_row"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("notify_mail_template")
