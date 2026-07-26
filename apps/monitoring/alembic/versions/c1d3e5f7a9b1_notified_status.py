# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""notified status (alerter sent-state)

Revision ID: c1d3e5f7a9b1
Revises: b7d9f1a3c5e7
Create Date: 2026-07-26

Sent-state tracking (docs/features/alert-sent-state.md): the status the alerter
last actually reported for a check. Backfilled with the current status so
existing warning/critical states are NOT re-notified on deploy — only future
discrepancies (suppressed transitions) trigger catch-up notifications.

Checks standing on 'unknown' at deploy time are backfilled from the alert log
instead: the last SENT new_status is exactly what notified_status means, and a
pre-deploy critical whose recovery arrives after the deploy would otherwise be
swallowed (resolve_notification treats notified='unknown' as unreported).
Unknown rows without a log entry keep 'unknown' — no phantom recovery.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d3e5f7a9b1"
down_revision: Union[str, Sequence[str], None] = "b7d9f1a3c5e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("monitor_states", sa.Column("notified_status", sa.String(), nullable=True))
    op.execute("UPDATE monitor_states SET notified_status = status WHERE status != 'unknown'")
    op.execute(
        """
        UPDATE monitor_states SET notified_status = COALESCE(
            (SELECT l.new_status FROM monitor_alert_log l
             WHERE l.check_id = monitor_states.check_id
             ORDER BY l.sent_at DESC LIMIT 1),
            'unknown')
        WHERE status = 'unknown'
        """
    )


def downgrade() -> None:
    op.drop_column("monitor_states", "notified_status")
