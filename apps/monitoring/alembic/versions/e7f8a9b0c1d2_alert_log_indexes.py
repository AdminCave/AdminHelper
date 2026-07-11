# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""alert_log indexes for cooldown, cleanup and log listing

The cooldown check (alert_rule_id + check_id + sent_at >= cutoff, on the alerter hot path), the daily
retention cleanup (sent_at < cutoff) and GET /alerts/log (ORDER BY sent_at DESC) all filter or sort
on sent_at, which was unindexed. Over 90 days of flapping checks the table grows to many thousands of
rows and these degrade to seq-scans/full-sorts. The composite index covers the cooldown query; the
sent_at index covers the cleanup and the log listing (5.19).

Revision ID: e7f8a9b0c1d2
Revises: b1a2c3d4e5f6
Create Date: 2026-07-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "b1a2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_alert_log_rule_check_sent",
        "monitor_alert_log",
        ["alert_rule_id", "check_id", "sent_at"],
    )
    op.create_index("ix_alert_log_sent_at", "monitor_alert_log", ["sent_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_alert_log_sent_at", table_name="monitor_alert_log")
    op.drop_index("ix_alert_log_rule_check_sent", table_name="monitor_alert_log")
