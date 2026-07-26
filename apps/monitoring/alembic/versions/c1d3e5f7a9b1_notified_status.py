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
    op.execute("UPDATE monitor_states SET notified_status = status")


def downgrade() -> None:
    op.drop_column("monitor_states", "notified_status")
