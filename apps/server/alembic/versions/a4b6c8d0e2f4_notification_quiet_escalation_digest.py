# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""notification_settings: quiet hours, escalation, digest and sound per person

Revision ID: a4b6c8d0e2f4
Revises: f3a5c7e9b1d2
Create Date: 2026-11-07

A person's channels gain quiet hours, the escalation of an unacknowledged critical
incident to a channel of their own, a daily or weekly e-mail digest and a sound for
critical toasts (R-1081). Every column has a server default that keeps the behaviour of
before: all off. A notification row records when its escalation went out, an incident
when it first turned critical. The downgrade hands the outbox entries waiting for the
digest back to the drain (status pending), so none is lost.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4b6c8d0e2f4"
down_revision: Union[str, Sequence[str], None] = "f3a5c7e9b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SETTINGS = (
    sa.Column("timezone", sa.String(), nullable=True),
    sa.Column("quiet_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("quiet_start", sa.String(5), nullable=False, server_default="22:00"),
    sa.Column("quiet_end", sa.String(5), nullable=False, server_default="07:00"),
    sa.Column("quiet_critical", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("escalation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("escalation_minutes", sa.Integer(), nullable=False, server_default="10"),
    sa.Column("escalation_channel", sa.String(), nullable=True),
    sa.Column("digest", sa.String(), nullable=False, server_default="off"),
    sa.Column("digest_last_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("sound_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
)


def upgrade() -> None:
    for column in _SETTINGS:
        op.add_column("notification_settings", column)
    op.add_column(
        "notification", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notification_incident",
        sa.Column("critical_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("UPDATE notification_outbox SET status = 'pending' WHERE status = 'digest'")
    op.drop_column("notification_incident", "critical_since")
    op.drop_column("notification", "escalated_at")
    for column in reversed(_SETTINGS):
        op.drop_column("notification_settings", column.name)
