# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""store tz-naive timestamp defaults in UTC, not the session timezone

Revision ID: d9e1f3a5b7c2
Revises: e7f8a9b0c1d2
Create Date: 2026-07-09

Every DateTime column in this service is tz-naive UTC (audit 2.29), and the app
writes them via utcnow_naive(). But ``server_default=now()`` coerces the
timestamptz into the naive column using the DB *session* timezone, and the stack
runs the postgres container with TZ=Europe/Berlin — so rows created from the
server_default stored Berlin local time, ~1-2h off UTC (NEU-8.14b, the monitoring
twin of server 8.14). Switch the defaults to ``timezone('UTC', now())``, which
yields the UTC wall-clock as a naive timestamp regardless of session TZ. Existing
rows keep their historical value; only new inserts are affected.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9e1f3a5b7c2"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The tz-naive DateTime columns with a now()-based server_default.
_COLUMNS: Sequence[tuple[str, str]] = (
    ("monitor_checks", "created_at"),
    ("monitor_checks", "updated_at"),
    ("monitor_states", "since"),
    ("monitor_alert_rules", "created_at"),
    ("monitor_alert_rules", "updated_at"),
    ("monitor_alert_log", "sent_at"),
    ("monitor_templates", "created_at"),
    ("monitor_templates", "updated_at"),
    ("monitor_agent_keys", "created_at"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(),
            server_default=sa.text("timezone('UTC', now())"),
        )


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(),
            server_default=sa.text("now()"),
        )
