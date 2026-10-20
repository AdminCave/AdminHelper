# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""alert quality: recovery hold and bell cooldown state

Revision ID: 3c66308d11a7
Revises: b9d1f3a5c7e9
Create Date: 2026-10-20

R-0424 (docs/features/monitoring-alert-quality.md):

- ``monitor_checks.consecutive_oks``: ok results in a row a check needs before it
  returns from warning/critical to ok. Every existing check gets 2, the new
  default, so its recovery arrives one interval later than before; 1 is the old
  behaviour.
- ``monitor_states.ok_count``: ok results in a row so far, the counterpart of
  ``fail_count``; starts at 0.
- ``monitor_states.hub_status`` / ``hub_sent_at``: the status the notification hub
  (the bell) last accepted for the check and when it last got a problem, the
  state of the per-check bell cooldown. ``hub_status`` is backfilled from
  ``notified_status`` where that is warning/critical: the bell only clears what it
  showed, and a problem reported before the deploy would otherwise never get its
  recovery there. ``hub_sent_at`` stays NULL, so no cooldown runs after the deploy.

The downgrade drops the four columns; ``consecutive_oks`` is then implicitly 1 again.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c66308d11a7"
down_revision: Union[str, Sequence[str], None] = "b9d1f3a5c7e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "monitor_checks",
        sa.Column("consecutive_oks", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "monitor_states",
        sa.Column("ok_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("monitor_states", sa.Column("hub_status", sa.String(), nullable=True))
    op.add_column("monitor_states", sa.Column("hub_sent_at", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE monitor_states SET hub_status = notified_status"
        " WHERE notified_status IN ('warning', 'critical')"
    )


def downgrade() -> None:
    op.drop_column("monitor_states", "hub_sent_at")
    op.drop_column("monitor_states", "hub_status")
    op.drop_column("monitor_states", "ok_count")
    op.drop_column("monitor_checks", "consecutive_oks")
