# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""servers.hostname: NULL means the address follows the server's name

Revision ID: b1c3d5e7f9a1
Revises: a4b6c8d0e2f4
Create Date: 2026-11-09

A server has one name, entered once (R-1210); its address is that name unless an own
address (an IP, an internal name) is stored. The column becomes nullable, and a stored
hostname that only repeats the name (or is empty) becomes NULL, so a later rename takes the
address along. The downgrade writes the name back into every NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c3d5e7f9a1"
down_revision: Union[str, Sequence[str], None] = "a4b6c8d0e2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("servers", "hostname", existing_type=sa.String(), nullable=True)
    op.execute(
        "UPDATE servers SET hostname = NULL "
        "WHERE trim(hostname) = '' OR lower(trim(hostname)) = lower(trim(name))"
    )


def downgrade() -> None:
    op.execute("UPDATE servers SET hostname = name WHERE hostname IS NULL")
    op.alter_column("servers", "hostname", existing_type=sa.String(), nullable=False)
