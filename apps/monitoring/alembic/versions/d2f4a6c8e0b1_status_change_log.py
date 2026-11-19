# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""status change log: every change of a damped status, taken over from the alert log

Revision ID: d2f4a6c8e0b1
Revises: a7c9e1f3b5d7
Create Date: 2026-11-19

R-1559 (docs/features/arch-monitoring-neu-p1.md, ADR 0004 §5):

- ``monitor_status_log``: one row per change of the damped status of a check
  (``object_key`` NULL) or of one of its objects, written whatever the alert
  rules say and kept 90 days.
- Every ``monitor_alert_log`` row is taken over as a check row
  (``origin = 'alert_log'``, ``at = sent_at``), so the history the alert log
  held does not go blank on the update. A change several rules were notified
  of arrives once per rule; the readers fold them as they did before.

The downgrade drops the table; ``monitor_alert_log`` stays as it is either way.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2f4a6c8e0b1"
down_revision: Union[str, Sequence[str], None] = "a7c9e1f3b5d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitor_status_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("check_id", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(length=200), nullable=True),
        sa.Column("old_status", sa.String(), nullable=False),
        sa.Column("new_status", sa.String(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["check_id"], ["monitor_checks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_status_log_check_at", "monitor_status_log", ["check_id", "at"], unique=False
    )
    op.create_index("ix_status_log_at", "monitor_status_log", ["at"], unique=False)
    op.execute(
        "INSERT INTO monitor_status_log (check_id, object_key, old_status, new_status, at, origin) "
        "SELECT check_id, NULL, old_status, new_status, sent_at, 'alert_log' "
        "FROM monitor_alert_log ORDER BY sent_at, id"
    )


def downgrade() -> None:
    op.drop_index("ix_status_log_at", table_name="monitor_status_log")
    op.drop_index("ix_status_log_check_at", table_name="monitor_status_log")
    op.drop_table("monitor_status_log")
