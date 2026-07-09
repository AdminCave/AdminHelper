# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""drop the dead connections.scaling_mode column

Revision ID: e5f7a1b3c9d0
Revises: c4d8e2f1a6b9
Create Date: 2026-07-09

connections.scaling_mode was a per-connection RDP scaling override that no
client ever consumed: the desktop Rust Connection struct has no such field, so
serde dropped it on sync and RDP scaling came solely from the global setting.
There is no UI to set it either, so the column was always NULL — a dead
half-feature. Remove it everywhere (schema, models, TS types) and drop the
column (8.14 -> tracked as 2.85).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f7a1b3c9d0"
down_revision: Union[str, Sequence[str], None] = "c4d8e2f1a6b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("connections", "scaling_mode")


def downgrade() -> None:
    op.add_column("connections", sa.Column("scaling_mode", sa.String(), nullable=True))
