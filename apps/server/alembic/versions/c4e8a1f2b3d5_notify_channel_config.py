# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""notify_channel_config: SMTP relay, Telegram token and private targets from the panel

Revision ID: c4e8a1f2b3d5
Revises: b7c9d1e3f5a7
Create Date: 2026-11-18

One row (id 1) an admin fills in the web panel (R-1531). The upgrade writes no row, so
every value still comes from .env until an admin sets one. The downgrade drops the
table: the panel values are gone and .env holds again.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8a1f2b3d5"
down_revision: Union[str, Sequence[str], None] = "b7c9d1e3f5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notify_channel_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("smtp_host", sa.String(length=255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("smtp_user", sa.String(length=255), nullable=True),
        sa.Column("smtp_password_enc", sa.LargeBinary(), nullable=True),
        sa.Column("smtp_from", sa.String(length=255), nullable=True),
        sa.Column("telegram_token_enc", sa.LargeBinary(), nullable=True),
        sa.Column("private_targets", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_notify_channel_config_single_row"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("notify_channel_config")
