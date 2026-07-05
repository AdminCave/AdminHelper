# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""partial unique index on frp_tunnels.visitor_port (STCP)

Closes a TOCTOU race in the tunnel create/update endpoints: the read-then-
assign of an STCP visitor_port could let two concurrent requests bind the same
port, generating a conflicting visitor.toml. The partial unique index is the
only race-free guard. HTTPS tunnels (visitor_port NULL) are excluded.

Pre-existing duplicate STCP visitor_port rows — which the old race could create — are defused
first: per port the oldest tunnel keeps it, the younger ones have visitor_port set to NULL (the
app reassigns on the next edit), so CREATE UNIQUE INDEX runs cleanly instead of crash-looping
the container on boot.

Revision ID: f1a2b3c4d5e6
Revises: e7b3c1a9d2f4
Create Date: 2026-06-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e7b3c1a9d2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Defuse duplicates first — else CREATE UNIQUE INDEX fails in the entrypoint and the server
    # container crash-loops (restart: unless-stopped) after an image update, recoverable only by
    # manual psql surgery. Per port the OLDEST tunnel keeps its visitor_port; the younger ones
    # lose it (NULL drops out of the partial index — the app reassigns on the next edit). Unlike
    # the content-identical template-assignment dedupe (4.44), these are REAL conflicts (distinct
    # tunnels), so free the port instead of deleting the row (4.64).
    op.execute(
        """
        UPDATE frp_tunnels SET visitor_port = NULL
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY visitor_port ORDER BY created_at NULLS LAST, id
                ) AS rn
                FROM frp_tunnels
                WHERE tunnel_type = 'stcp' AND visitor_port IS NOT NULL
            ) d WHERE d.rn > 1
        )
        """
    )
    op.create_index(
        "uq_frp_tunnel_visitor_port",
        "frp_tunnels",
        ["visitor_port"],
        unique=True,
        postgresql_where=sa.text("tunnel_type = 'stcp' AND visitor_port IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_frp_tunnel_visitor_port", table_name="frp_tunnels")
