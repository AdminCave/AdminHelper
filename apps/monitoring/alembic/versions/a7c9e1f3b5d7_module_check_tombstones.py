# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""module checks: tombstones and the hash of their catalog definition

Revision ID: a7c9e1f3b5d7
Revises: c1e3a5b7d9f0
Create Date: 2026-11-14

R-1264 (docs/features/kern-monitoring-20.md):

- ``monitor_module_tombstones``: a module check the admin deleted on one server,
  one row per (server, module, instance, check key), so a catalog sync or an
  adopt does not create it again.
- ``monitor_checks.module_check_hash``: the hash of the catalog definition a
  module check was made from; NULL for every check from before this revision
  and for every check that is no module check.

Purely additive; the downgrade drops the table and the column.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c9e1f3b5d7"
down_revision: Union[str, Sequence[str], None] = "c1e3a5b7d9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UTC_NOW = sa.text("timezone('UTC', now())")


def upgrade() -> None:
    op.create_table(
        "monitor_module_tombstones",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("module_id", sa.String(), nullable=False),
        sa.Column("instance_key", sa.String(), nullable=False),
        sa.Column("check_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=_UTC_NOW, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_id",
            "module_id",
            "instance_key",
            "check_key",
            name="uq_module_tombstone_server_module_instance_check",
        ),
    )
    op.create_index(
        op.f("ix_monitor_module_tombstones_server_id"),
        "monitor_module_tombstones",
        ["server_id"],
        unique=False,
    )
    op.add_column("monitor_checks", sa.Column("module_check_hash", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("monitor_checks", "module_check_hash")
    op.drop_index(
        op.f("ix_monitor_module_tombstones_server_id"), table_name="monitor_module_tombstones"
    )
    op.drop_table("monitor_module_tombstones")
