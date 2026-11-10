# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""connections.name: a connection of a server keeps only its own text

Revision ID: c2d4e6f8a0b2
Revises: b1c3d5e7f9a1
Create Date: 2026-11-09

A connection of a server shows a display name derived from the server's name (R-1210);
its name column holds only the own text in it, '' for none. Names that only copied
something are emptied (Kevin 2026-11-09, 4a): the server's name or address, and the name
of the tunnel leading to the connection, also as "{tunnel} (via FRP)", the name the
auto-connection got. Case and outer whitespace aside. Every other name stays as the own
text. A data migration only; the downgrade writes the display name into the emptied rows,
as the columns of before can show nothing else.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d4e6f8a0b2"
down_revision: Union[str, Sequence[str], None] = "b1c3d5e7f9a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE connections AS c SET name = ''
        FROM servers AS s
        WHERE c.server_id = s.id
          AND (
            lower(trim(c.name)) IN (lower(trim(s.name)), lower(trim(coalesce(s.hostname, s.name))))
            OR EXISTS (
              SELECT 1 FROM frp_tunnels AS t
              WHERE t.connection_id = c.id
                AND lower(trim(c.name)) IN (
                  lower(trim(t.name)), lower(trim(t.name)) || ' (via frp)'
                )
            )
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE connections AS c SET name = s.name || ' · ' || (
            CASE c.kind WHEN 'ssh' THEN 'SSH' WHEN 'rdp' THEN 'RDP' WHEN 'web' THEN 'Web'
            ELSE c.kind END
          ) || (
            CASE WHEN EXISTS (SELECT 1 FROM frp_tunnels AS t WHERE t.connection_id = c.id)
            THEN ' (FRP)' ELSE '' END
          )
        FROM servers AS s
        WHERE c.server_id = s.id AND trim(c.name) = ''
        """
    )
