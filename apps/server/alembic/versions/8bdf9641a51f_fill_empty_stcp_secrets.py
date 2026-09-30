# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""give every stcp tunnel without a secret its own

Revision ID: 8bdf9641a51f
Revises: e5f7a1b3c9d0
Create Date: 2026-09-30

An update could store an stcp tunnel with secret_key NULL or "", and the
generator now leaves such a tunnel out of the frpc and visitor config. Each of
these rows gets its own random secret here, so the tunnels stay in the config.
The agent picks the new config up through the provision hash; a running
desktop visitor of such a tunnel needs a tunnel restart.
"""

import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8bdf9641a51f"
down_revision: Union[str, Sequence[str], None] = "e5f7a1b3c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id FROM frp_tunnels"
            " WHERE tunnel_type = 'stcp' AND (secret_key IS NULL OR secret_key = '')"
        )
    ).fetchall()
    # One value per row, drawn in Python: a shared value or an SQL random()
    # would not be the 256-bit secret FrpTunnel.generate_secret() stands for.
    for (tunnel_id,) in rows:
        conn.execute(
            sa.text("UPDATE frp_tunnels SET secret_key = :secret WHERE id = :id"),
            {"secret": secrets.token_urlsafe(32), "id": tunnel_id},
        )


def downgrade() -> None:
    # No-op: a filled secret is valid under every earlier revision, and which
    # rows were empty before is not recorded anywhere.
    pass
