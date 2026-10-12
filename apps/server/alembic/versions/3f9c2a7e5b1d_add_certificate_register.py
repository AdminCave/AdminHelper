# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""add the certificate register: device lines, issued certificates, install time

Revision ID: 3f9c2a7e5b1d
Revises: 8bdf9641a51f
Create Date: 2026-10-11

Every client certificate the ca-issuer signs is recorded by its fingerprint and
belongs to a device line: enrollment opens a line, a renewal stays on it, and a
line can be revoked on its own. certificate_register_state holds one row with the
time the register was installed; certificates issued before it are taken over at
first contact during the transition. Nothing is backfilled, because no issued
certificate was recorded before this revision.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f9c2a7e5b1d"
down_revision: Union[str, Sequence[str], None] = "8bdf9641a51f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UTC_NOW = sa.text("timezone('UTC', now())")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "device_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("legacy", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_UTC_NOW),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_reason", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_lines_subject_scope", "device_lines", ["subject_id", "scope"])
    op.create_table(
        "issued_certificates",
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("line_id", sa.String(length=36), nullable=False),
        sa.Column("serial", sa.String(length=40), nullable=False),
        sa.Column("not_before", sa.DateTime(), nullable=False),
        sa.Column("not_after", sa.DateTime(), nullable=False),
        sa.Column("renewed_from", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_UTC_NOW),
        sa.ForeignKeyConstraint(["line_id"], ["device_lines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("fingerprint"),
    )
    op.create_index(op.f("ix_issued_certificates_line_id"), "issued_certificates", ["line_id"])
    op.create_index(op.f("ix_issued_certificates_not_after"), "issued_certificates", ["not_after"])
    op.create_table(
        "certificate_register_state",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("installed_at", sa.DateTime(), nullable=False, server_default=_UTC_NOW),
        sa.PrimaryKeyConstraint("id"),
    )
    # The install time is the server default: the moment this revision runs.
    op.execute("INSERT INTO certificate_register_state (id) VALUES (1)")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("certificate_register_state")
    op.drop_index(op.f("ix_issued_certificates_not_after"), table_name="issued_certificates")
    op.drop_index(op.f("ix_issued_certificates_line_id"), table_name="issued_certificates")
    op.drop_table("issued_certificates")
    op.drop_index("ix_device_lines_subject_scope", table_name="device_lines")
    op.drop_table("device_lines")
