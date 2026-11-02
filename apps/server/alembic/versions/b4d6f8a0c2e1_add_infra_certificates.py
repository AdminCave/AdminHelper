# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""add infra_certificates: the infrastructure certificates the ca-issuer holds

Revision ID: b4d6f8a0c2e1
Revises: a7c9e1b3d5f2
Create Date: 2026-10-31

The server cannot read the PKI volume, so the ca-issuer writes name, subject,
fingerprint and validity of its root, intermediates, gateway and frps
certificate here on every start; the server shows them and warns before they
expire. Nothing else refers to the table: the downgrade only drops it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d6f8a0c2e1"
down_revision: Union[str, Sequence[str], None] = "a7c9e1b3d5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UTC_NOW = sa.text("timezone('UTC', now())")


def upgrade() -> None:
    op.create_table(
        "infra_certificates",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("not_before", sa.DateTime(), nullable=False),
        sa.Column("not_after", sa.DateTime(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False, server_default=_UTC_NOW),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("infra_certificates")
