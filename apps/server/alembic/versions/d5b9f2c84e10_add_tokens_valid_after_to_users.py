# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""add tokens_valid_after to users (revoke JWTs on password reset)

Revision ID: d5b9f2c84e10
Revises: c3a7e1f50b2d
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5b9f2c84e10'
down_revision: Union[str, Sequence[str], None] = 'c3a7e1f50b2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('tokens_valid_after', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'tokens_valid_after')
