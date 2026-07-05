# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""rename frp_provision_tokens to provision_tokens

Revision ID: 0494a8f377ef
Revises: 1d8276d3aa26
Create Date: 2026-05-02 18:29:13.806123

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0494a8f377ef"
down_revision: Union[str, Sequence[str], None] = "1d8276d3aa26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A real rename that carries the rows over. The original auto-generated create_table +
    # drop_table silently destroyed every pending provision token — a running agent onboarding
    # (or an already-handed-out token) would then fail with a confusing 401/invalid-token. The
    # migration is already shipped, so this only helps not-yet-migrated deployments; it must not
    # be copied as a template for future renames (4.62).
    op.rename_table("frp_provision_tokens", "provision_tokens")


def downgrade() -> None:
    """Downgrade schema."""
    op.rename_table("provision_tokens", "frp_provision_tokens")
