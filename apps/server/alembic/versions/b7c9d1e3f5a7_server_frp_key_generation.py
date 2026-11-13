# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""servers.frp_key_generation: the generation of the host's frps proxy key

Revision ID: b7c9d1e3f5a7
Revises: d3e5f7a9b1c3
Create Date: 2026-11-13

The proxy key of a host comes from SECRET_KEY, its server ID and this generation
(frp/proxy_key.py). Every existing row gets 0, which derives the key it had before, so the
upgrade changes no host's key. The downgrade drops the column: every host falls back to the
key of generation 0 and fetches it with its next frpc.toml.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c9d1e3f5a7"
down_revision: Union[str, Sequence[str], None] = "d3e5f7a9b1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "servers",
        sa.Column("frp_key_generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("servers", "frp_key_generation")
