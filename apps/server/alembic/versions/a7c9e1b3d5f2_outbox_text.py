# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""give outbox entries a text of their own (title, body)

Revision ID: a7c9e1b3d5f2
Revises: c3e5a7b9d1f2
Create Date: 2026-10-20

A bundled event (several servers at once) lists in the bell every server the
user's subscriptions cover, but an e-mail or Telegram message may only name the
servers of the subscriptions that asked for that channel. The outbox entry
therefore carries its own title and body; NULL keeps the text of the
notification row, as for every entry written before this revision.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c9e1b3d5f2"
down_revision: Union[str, Sequence[str], None] = "c3e5a7b9d1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notification_outbox", sa.Column("title", sa.String(), nullable=True))
    op.add_column("notification_outbox", sa.Column("body", sa.Text(), nullable=True))


def downgrade() -> None:
    """A pending entry with a text of its own ends as ``failed``, the drain's
    terminal state, before the columns go. Without its text it would go out with
    the notification's, which may name servers that only a subscription without
    this channel covers. A Telegram entry stays pending until a Telegram drain
    exists, so it would leak even after a later upgrade: its title is NULL then.
    Entries without a text of their own and entries already sent or failed stay
    as they are."""
    outbox = sa.table(
        "notification_outbox",
        sa.column("status", sa.String()),
        sa.column("last_error", sa.Text()),
        sa.column("title", sa.String()),
    )
    op.execute(
        outbox.update()
        .where(outbox.c.status == "pending", outbox.c.title.is_not(None))
        .values(status="failed", last_error="own text dropped by downgrade")
    )
    op.drop_column("notification_outbox", "body")
    op.drop_column("notification_outbox", "title")
