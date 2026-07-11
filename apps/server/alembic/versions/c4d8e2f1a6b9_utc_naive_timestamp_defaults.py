# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""store tz-naive timestamp defaults in UTC, not the session timezone

Revision ID: c4d8e2f1a6b9
Revises: a7c3efba142a
Create Date: 2026-07-09

The tz-naive DateTime columns store UTC by convention (F7), and the application
writes them via utcnow_naive(). But ``server_default=now()`` coerces the
timestamptz into the naive column using the DB *session* timezone, and the stack
runs the postgres container with TZ=Europe/Berlin — so rows created from the
server_default stored Berlin local time, ~1-2h off the app's UTC (8.14). Switch
the defaults to ``timezone('UTC', now())`` (the DB-side twin of utcnow_naive),
which yields the UTC wall-clock as a naive timestamp regardless of session TZ.
Existing rows keep their historical value; only new inserts are affected.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d8e2f1a6b9"
down_revision: Union[str, Sequence[str], None] = "a7c3efba142a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The tz-naive DateTime columns with a now()-based server_default (the aware
# audit_log / notification* columns use TIMESTAMPTZ and are correct as-is).
_COLUMNS: Sequence[tuple[str, str]] = (
    ("ansible_playbooks", "created_at"),
    ("api_keys", "created_at"),
    ("provision_tokens", "created_at"),
    ("servers", "created_at"),
    ("connections", "created_at"),
    ("frp_server_config", "created_at"),
    ("frp_server_config", "updated_at"),
    ("frp_tunnels", "created_at"),
    ("hooks", "created_at"),
    ("users", "created_at"),
    ("enrollment_tokens", "created_at"),
    ("revoked_identities", "revoked_at"),
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
