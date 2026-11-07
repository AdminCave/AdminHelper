# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""notification_settings: the matrix severity x channel replaces the channel ticks

Revision ID: f3a5c7e9b1d2
Revises: c8e2f4a6b0d1
Create Date: 2026-11-07

A person's channels move from the ticks of each rule (channel_email, channel_telegram) to
one matrix per person (R-1080). A ticked channel goes into every row at or above the
rule's min_severity and into ok (the all-clear went out on the channel of the rule that
reported the problem); the desktop goes into every row, as toasts came for everything.
The downgrade ticks a channel on every rule of the person when it is in any row of the
matrix and not switched off: the matrix is finer than the ticks, so that way loses detail.
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a5c7e9b1d2"
down_revision: Union[str, Sequence[str], None] = "c8e2f4a6b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEVERITIES = ("info", "warning", "critical")
_ROWS = ("critical", "warning", "info", "ok")
_CHANNELS = ("desktop", "email", "ntfy", "telegram", "webhook")


def _matrix(rules: list[tuple[str, bool, bool, bool]]) -> dict[str, list[str]]:
    """The matrix of one person from their rules (min_severity, email, telegram,
    enabled). An unknown min_severity counts as info, as the resolver never lets it
    suppress anything."""
    rows: dict[str, set[str]] = {row: {"desktop"} for row in _ROWS}
    for min_severity, email, telegram, enabled in rules:
        if not enabled:
            continue
        floor = _SEVERITIES.index(min_severity) if min_severity in _SEVERITIES else 0
        for channel, ticked in (("email", email), ("telegram", telegram)):
            if not ticked:
                continue
            for severity in _SEVERITIES[floor:]:
                rows[severity].add(channel)
            rows["ok"].add(channel)
    return {row: [c for c in _CHANNELS if c in rows[row]] for row in _ROWS}


def upgrade() -> None:
    op.create_table(
        "notification_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ntfy_url", sa.Text(), nullable=True),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column("matrix", sa.Text(), nullable=False),
        sa.Column("disabled_channels", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("muted_categories", sa.Text(), nullable=False, server_default="[]"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    conn = op.get_bind()
    rules: dict[int, list[tuple[str, bool, bool, bool]]] = {}
    for user_id, min_severity, email, telegram, enabled in conn.execute(
        sa.text(
            "SELECT user_id, min_severity, channel_email, channel_telegram, enabled"
            " FROM notification_subscription ORDER BY user_id, id"
        )
    ):
        rules.setdefault(user_id, []).append((min_severity, email, telegram, enabled))
    for user_id, user_rules in rules.items():
        conn.execute(
            sa.text("INSERT INTO notification_settings (user_id, matrix) VALUES (:u, :m)"),
            {"u": user_id, "m": json.dumps(_matrix(user_rules))},
        )
    op.drop_column("notification_subscription", "channel_email")
    op.drop_column("notification_subscription", "channel_telegram")


def downgrade() -> None:
    for column in ("channel_email", "channel_telegram"):
        op.add_column(
            "notification_subscription",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    conn = op.get_bind()
    for user_id, matrix, disabled in conn.execute(
        sa.text("SELECT user_id, matrix, disabled_channels FROM notification_settings")
    ):
        used = {c for row in json.loads(matrix).values() for c in row} - set(json.loads(disabled))
        conn.execute(
            sa.text(
                "UPDATE notification_subscription SET channel_email = :e,"
                " channel_telegram = :t WHERE user_id = :u"
            ),
            {"e": "email" in used, "t": "telegram" in used, "u": user_id},
        )
    # The default only filled the rows; the columns had none before (a7c3efba142a).
    for column in ("channel_email", "channel_telegram"):
        op.alter_column("notification_subscription", column, server_default=None)
    op.drop_table("notification_settings")
