# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""unique constraint on (template_id, server_id)

Closes a TOCTOU race in the template-assign endpoint: the read-then-insert
check could let two concurrent requests create duplicate assignments. The DB
constraint is the only race-free guard.

Pre-existing duplicate (template_id, server_id) rows — which the old race could create — are
deduplicated first (one row per pair survives; they are identical bar id), so ADD CONSTRAINT
runs cleanly instead of crash-looping the container on boot.

Revision ID: b1a2c3d4e5f6
Revises: c85e6dacd792
Create Date: 2026-06-15 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1a2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "c85e6dacd792"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Remove content-identical duplicates (same template/server, copied name/hostname fields; the
    # now-closed TOCTOU race in the assign endpoint could create them) before adding the
    # constraint — else ADD CONSTRAINT fails and the monitoring container crash-loops on boot
    # (docker-entrypoint.sh runs `alembic upgrade head` under `set -e`). The lexicographically
    # smaller id survives; deletion is lossless since the rows are identical bar id (4.44).
    op.execute(
        """
        DELETE FROM monitor_template_assignments a
        USING monitor_template_assignments b
        WHERE a.template_id = b.template_id
          AND a.server_id = b.server_id
          AND a.id > b.id
        """
    )
    op.create_unique_constraint(
        "uq_assignment_template_server",
        "monitor_template_assignments",
        ["template_id", "server_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_assignment_template_server",
        "monitor_template_assignments",
        type_="unique",
    )
