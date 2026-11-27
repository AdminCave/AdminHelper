# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""rule layer of module probe checks

Revision ID: b6d8f0a2c4e6
Revises: f4b6d8a0c2e4
Create Date: 2026-11-27

The catalog rules a module's probe check is bound to and the admin's overrides over
them (docs/features/arch-monitoring-neu-p1d.md, R-1638). The column only: filling it
needs the catalog in code, so record_rule_layers does it at start-up.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6d8f0a2c4e6"
down_revision: Union[str, Sequence[str], None] = "f4b6d8a0c2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("monitor_checks", sa.Column("rule_layer", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("monitor_checks", "rule_layer")
