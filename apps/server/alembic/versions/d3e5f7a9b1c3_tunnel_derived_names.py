# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""frp_tunnels.name: the own text of the display name, no longer unique

Revision ID: d3e5f7a9b1c3
Revises: c2d4e6f8a0b2
Create Date: 2026-11-09

frpc and the visitor know a tunnel by its ID (R-1210), so its name no longer has to be
unique; it holds the own text of the display name the server derives, '' for none. Names
that only copied the server (its name, its address, or the old proxy-name pattern
"{server}-{protocol}" / "{server}-{tunnel_type}") are emptied (Kevin 2026-11-09, 4a), case
and outer whitespace aside; every other name stays. The downgrade gives every emptied row the
pattern back and makes names unique again by appending the ID to each one used more than once.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e5f7a9b1c3"
down_revision: Union[str, Sequence[str], None] = "c2d4e6f8a0b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The unnamed UniqueConstraint("name") of the initial schema: Postgres names it so.
    op.drop_constraint("frp_tunnels_name_key", "frp_tunnels", type_="unique")
    op.execute(
        """
        UPDATE frp_tunnels AS t SET name = ''
        FROM servers AS s
        WHERE t.server_id = s.id
          AND lower(trim(t.name)) IN (
            lower(trim(s.name)),
            lower(trim(coalesce(s.hostname, s.name))),
            lower(trim(s.name)) || '-' || lower(t.protocol),
            lower(trim(s.name)) || '-' || lower(t.tunnel_type)
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE frp_tunnels AS t SET name = s.name || '-' || t.protocol
        FROM servers AS s
        WHERE t.server_id = s.id AND trim(t.name) = ''
        """
    )
    op.execute(
        """
        UPDATE frp_tunnels AS t SET name = t.name || '-' || t.id
        WHERE (SELECT count(*) FROM frp_tunnels AS o WHERE o.name = t.name) > 1
        """
    )
    op.create_unique_constraint("frp_tunnels_name_key", "frp_tunnels", ["name"])
