# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""add connections.options

Revision ID: a7c3e9d1f5b2
Revises: b4d6f8a0c2e1
Create Date: 2026-11-05

Per-connection SSH and RDP options (R-1066) as one JSON object. A column of its own rather
than extra_data: extra_data keeps whatever an unknown client sends, unchecked, while the
options become command-line arguments on the desktop and are validated at the API.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e9d1f5b2"
down_revision: Union[str, Sequence[str], None] = "b4d6f8a0c2e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("options", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("connections", "options")
