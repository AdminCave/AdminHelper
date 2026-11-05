# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""add notification incidents: the bell folds events into incidents

Revision ID: d3b5f7a9c1e4
Revises: c1a7e3f5b9d2
Create Date: 2026-11-05

An incident (R-1079) collects the events of one check, or of one bundle of servers,
or one keyless notice of the server; the team shares its state, acknowledgement and
history. Every recipient keeps one bell row per incident (unique per user and
incident) that a ping moves up by notified_at. A person can mute an incident (on the
row) or a server (notification_server_mute) and hide a row.

notified_at starts as created_at for the rows that exist, so the feed keeps its order.
Rows from before have no incident and stay as they are. The downgrade drops the four
tables and the four columns; the incidents, their history and every mute are lost,
the bell rows themselves stay.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3b5f7a9c1e4"
down_revision: Union[str, Sequence[str], None] = "c1a7e3f5b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "notification_incident",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("notified_severity", sa.String(), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("rules", sa.Text(), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("first_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("acked_by", sa.Integer(), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["acked_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notification_incident_key"), "notification_incident", ["key"], unique=False
    )
    op.create_table(
        "notification_incident_member",
        sa.Column("incident_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["notification_incident.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("incident_id", "key"),
    )
    op.create_index(
        op.f("ix_notification_incident_member_key"),
        "notification_incident_member",
        ["key"],
        unique=False,
    )
    op.create_table(
        "notification_incident_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("incident_id", sa.BigInteger(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("server_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["notification_incident.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notification_incident_event_incident_id"),
        "notification_incident_event",
        ["incident_id"],
        unique=False,
    )
    op.create_table(
        "notification_server_mute",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.String(), nullable=False),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "server_id"),
    )

    op.add_column("notification", sa.Column("incident_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "notification_incident_id_fkey",
        "notification",
        "notification_incident",
        ["incident_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_notification_incident_id"), "notification", ["incident_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_notification_user_incident", "notification", ["user_id", "incident_id"]
    )
    # Without a default first: a default now() would date every old row to the upgrade.
    op.add_column("notification", sa.Column("notified_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE notification SET notified_at = created_at")
    op.alter_column("notification", "notified_at", nullable=False, server_default=_NOW)
    op.create_index(
        op.f("ix_notification_notified_at"), "notification", ["notified_at"], unique=False
    )
    op.add_column(
        "notification", sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("notification", sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("notification", "hidden_at")
    op.drop_column("notification", "muted_until")
    op.drop_index(op.f("ix_notification_notified_at"), table_name="notification")
    op.drop_column("notification", "notified_at")
    op.drop_constraint("uq_notification_user_incident", "notification", type_="unique")
    op.drop_index(op.f("ix_notification_incident_id"), table_name="notification")
    op.drop_constraint("notification_incident_id_fkey", "notification", type_="foreignkey")
    op.drop_column("notification", "incident_id")
    op.drop_table("notification_server_mute")
    op.drop_index(
        op.f("ix_notification_incident_event_incident_id"),
        table_name="notification_incident_event",
    )
    op.drop_table("notification_incident_event")
    op.drop_index(
        op.f("ix_notification_incident_member_key"), table_name="notification_incident_member"
    )
    op.drop_table("notification_incident_member")
    op.drop_index(op.f("ix_notification_incident_key"), table_name="notification_incident")
    op.drop_table("notification_incident")
