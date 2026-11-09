# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""module discovery: inventory, findings and module checks

Revision ID: b8d0f2a4c6e8
Revises: 3c66308d11a7
Create Date: 2026-11-09

R-1223 (docs/features/arch-monitoring-module.md):

- ``monitor_discovery``: per server the inventory its agent's last discovery
  reported, the credentials it holds (references only) and when the next discovery
  is due. ``scan_requested_at`` is the "scan now" button.
- ``monitor_findings``: the inbox of the catalog match, one row per (server, module,
  instance) with kind new/changed/gone and status open/adopted/dismissed.
- ``monitor_checks`` gains ``module_id`` (indexed), ``module_instance``,
  ``module_check_key`` and ``silent``. Every existing check gets ``silent = false``
  and no module: it alerts exactly as before.

Purely additive; the downgrade drops both tables and the four columns.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d0f2a4c6e8"
down_revision: Union[str, Sequence[str], None] = "3c66308d11a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UTC_NOW = sa.text("timezone('UTC', now())")


def upgrade() -> None:
    op.create_table(
        "monitor_discovery",
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("scanned_at", sa.DateTime(), nullable=True),
        sa.Column("next_scan_at", sa.DateTime(), nullable=True),
        sa.Column("scan_requested_at", sa.DateTime(), nullable=True),
        sa.Column("inventory", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("credentials", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(), server_default=_UTC_NOW, nullable=True),
        sa.PrimaryKeyConstraint("server_id"),
    )
    op.create_table(
        "monitor_findings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("module_id", sa.String(), nullable=False),
        sa.Column("instance_key", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("summary", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("catalog_version", sa.String(), nullable=False),
        sa.Column("first_seen", sa.DateTime(), server_default=_UTC_NOW, nullable=False),
        sa.Column("last_seen", sa.DateTime(), server_default=_UTC_NOW, nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_id", "module_id", "instance_key", name="uq_finding_server_module_instance"
        ),
    )
    op.create_index(op.f("ix_monitor_findings_server_id"), "monitor_findings", ["server_id"])
    op.add_column("monitor_checks", sa.Column("module_id", sa.String(), nullable=True))
    op.add_column("monitor_checks", sa.Column("module_instance", sa.String(), nullable=True))
    op.add_column("monitor_checks", sa.Column("module_check_key", sa.String(), nullable=True))
    op.add_column(
        "monitor_checks",
        sa.Column("silent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(op.f("ix_monitor_checks_module_id"), "monitor_checks", ["module_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_monitor_checks_module_id"), table_name="monitor_checks")
    op.drop_column("monitor_checks", "silent")
    op.drop_column("monitor_checks", "module_check_key")
    op.drop_column("monitor_checks", "module_instance")
    op.drop_column("monitor_checks", "module_id")
    op.drop_index(op.f("ix_monitor_findings_server_id"), table_name="monitor_findings")
    op.drop_table("monitor_findings")
    op.drop_table("monitor_discovery")
