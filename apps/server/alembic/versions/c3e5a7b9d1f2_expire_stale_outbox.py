# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""let pending outbox entries older than seven days expire

Revision ID: c3e5a7b9d1f2
Revises: 3f9c2a7e5b1d
Create Date: 2026-10-17

From v0.38.0 on the scheduler process ran none of its DB jobs, the outbox drain
included, so e-mail notifications queued up for months. Once the scheduler works
again, its first drain would send that backlog to the addresses stored back then.
Pending entries older than seven days end here as ``failed`` — the drain's
terminal state, which it never picks up again — with a last_error that says why;
younger ones go out as usual. attempts stays as it is, and the bell feed
(notification) is not touched.
"""

from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e5a7b9d1f2"
down_revision: Union[str, Sequence[str], None] = "3f9c2a7e5b1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MAX_AGE = timedelta(days=7)


def upgrade() -> None:
    outbox = sa.table(
        "notification_outbox",
        sa.column("status", sa.String()),
        sa.column("last_error", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    # An aware cutoff: created_at is TIMESTAMPTZ, and the migration's session runs
    # in the database's own zone (Europe/Berlin in the stack), which would read a
    # naive value as local time.
    cutoff = datetime.now(timezone.utc) - _MAX_AGE
    op.execute(
        outbox.update()
        .where(outbox.c.status == "pending", outbox.c.created_at < cutoff)
        .values(status="failed", last_error="expired before delivery")
    )


def downgrade() -> None:
    """No-op: a failed entry is valid under every earlier revision. Making these
    entries pending again would re-queue the very backlog this revision keeps from
    going out, and the last_error they carried before is not recorded anywhere."""
