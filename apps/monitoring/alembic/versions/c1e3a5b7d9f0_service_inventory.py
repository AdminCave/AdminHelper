# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""service details: inventory and error lines per server

Revision ID: c1e3a5b7d9f0
Revises: b8d0f2a4c6e8
Create Date: 2026-11-12

R-1226 (docs/features/arch-monitoring-ui-3.md):

- ``monitor_service_inventory``: per server the full service inventory its agent
  last reported, and ``log_lines``, the switch for the error lines of failed
  services (on unless the admin turns it off).
- ``monitor_service_logs``: the redacted error lines of a failed service, one row
  per (server, unit), kept while the unit stays failed.

Purely additive; the downgrade drops both tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1e3a5b7d9f0"
down_revision: Union[str, Sequence[str], None] = "b8d0f2a4c6e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UTC_NOW = sa.text("timezone('UTC', now())")


def upgrade() -> None:
    op.create_table(
        "monitor_service_inventory",
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("reported_at", sa.DateTime(), nullable=True),
        sa.Column("services", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("log_lines", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("server_id"),
    )
    op.create_table(
        "monitor_service_logs",
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("since", sa.DateTime(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), server_default=_UTC_NOW, nullable=False),
        sa.Column("lines", sa.Text(), nullable=False, server_default="[]"),
        sa.PrimaryKeyConstraint("server_id", "unit"),
    )


def downgrade() -> None:
    op.drop_table("monitor_service_logs")
    op.drop_table("monitor_service_inventory")
