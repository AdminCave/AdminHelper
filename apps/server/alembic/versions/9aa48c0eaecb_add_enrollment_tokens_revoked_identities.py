# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""add enrollment tokens + revoked identities (PKI plane, ADR 0001)

The server mints one-time enrollment tokens and writes identity revocations;
the ca-issuer reads/consumes them. Additive — nothing existing depends on these.

Revision ID: 9aa48c0eaecb
Revises: a258973bb7fd
Create Date: 2026-06-11 11:28:59.412995

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9aa48c0eaecb"
down_revision: Union[str, Sequence[str], None] = "a258973bb7fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "enrollment_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("hashed_token", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("browser", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hashed_token"),
    )
    op.create_table(
        "revoked_identities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id", "scope", name="uq_revoked_subject_scope"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("revoked_identities")
    op.drop_table("enrollment_tokens")
