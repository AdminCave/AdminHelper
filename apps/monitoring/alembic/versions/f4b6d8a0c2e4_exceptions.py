# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""exceptions: scope x effect x duration, with the maintenance windows taken over

Revision ID: f4b6d8a0c2e4
Revises: e3a5c7e9f1b2
Create Date: 2026-11-25

R-1636 (docs/features/arch-monitoring-neu-p1b.md, ADR 0004 §7):

- ``monitor_exceptions``: one row per exception. Every row of
  ``monitor_maintenance`` is copied with its id: server_id NULL becomes scope
  ``all``, otherwise ``server``; effect ``no_notify``; kind, the time fields,
  note (as reason) and created_at unchanged; enabled NULL becomes false (the
  evaluator skipped such rows already); origin ``migration``. The copy skips
  ids that are already there. ``monitor_maintenance`` itself stays as it is.
- ``monitor_object_state.excluded``: the setting that excludes an object.

The downgrade writes the facade's state back: it empties
``monitor_maintenance`` and inserts every maintenance-shaped exception (scope
server with a server_id, or all; no_notify, once or weekly, not ended), then
drops the column and the table. Exceptions of any other shape are lost on that way; the full way back
is restore.sh (ADR 0004 §10).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4b6d8a0c2e4"
down_revision: Union[str, Sequence[str], None] = "e3a5c7e9f1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitor_exceptions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("scope_kind", sa.String(), nullable=False),
        sa.Column("server_id", sa.String(), nullable=True),
        sa.Column("check_id", sa.String(), nullable=True),
        sa.Column("check_type", sa.String(), nullable=True),
        sa.Column("effect", sa.String(), nullable=False),
        sa.Column("duration_kind", sa.String(), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("weekdays", sa.String(), nullable=True),
        sa.Column("start_time", sa.String(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(), server_default="UTC", nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_by_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_by_id", sa.String(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("ended_by", sa.String(), nullable=True),
        sa.Column("ended_by_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["check_id"], ["monitor_checks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_monitor_exceptions_server_id"), "monitor_exceptions", ["server_id"])
    op.create_index(op.f("ix_monitor_exceptions_check_id"), "monitor_exceptions", ["check_id"])
    op.add_column(
        "monitor_object_state", sa.Column("excluded", sa.String(length=40), nullable=True)
    )
    op.execute(
        "INSERT INTO monitor_exceptions"
        " (id, scope_kind, server_id, effect, duration_kind, starts_at, ends_at, weekdays,"
        " start_time, duration_minutes, timezone, reason, enabled, origin, created_at)"
        " SELECT m.id,"
        " CASE WHEN m.server_id IS NULL THEN 'all' ELSE 'server' END,"
        " m.server_id, 'no_notify', m.kind, m.starts_at, m.ends_at, m.weekdays,"
        " m.start_time, m.duration_minutes, m.timezone, m.note, COALESCE(m.enabled, false),"
        " 'migration', m.created_at"
        " FROM monitor_maintenance m"
        " WHERE NOT EXISTS (SELECT 1 FROM monitor_exceptions e WHERE e.id = m.id)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM monitor_maintenance")
    op.execute(
        "INSERT INTO monitor_maintenance"
        " (id, server_id, note, kind, starts_at, ends_at, weekdays, start_time,"
        " duration_minutes, timezone, enabled, created_at)"
        " SELECT id, CASE WHEN scope_kind = 'all' THEN NULL ELSE server_id END, reason,"
        " duration_kind, starts_at, ends_at, weekdays, start_time, duration_minutes,"
        " timezone, enabled, created_at"
        " FROM monitor_exceptions"
        " WHERE (scope_kind = 'all' OR (scope_kind = 'server' AND server_id IS NOT NULL))"
        " AND effect = 'no_notify'"
        " AND duration_kind IN ('once', 'weekly') AND ended_at IS NULL"
    )
    op.drop_column("monitor_object_state", "excluded")
    op.drop_index(op.f("ix_monitor_exceptions_check_id"), table_name="monitor_exceptions")
    op.drop_index(op.f("ix_monitor_exceptions_server_id"), table_name="monitor_exceptions")
    op.drop_table("monitor_exceptions")
