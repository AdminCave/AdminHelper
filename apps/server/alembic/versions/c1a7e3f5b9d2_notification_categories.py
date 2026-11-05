# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""notification categories after the bell mockup: lifecycle splits into tunnel, security, agent

Revision ID: c1a7e3f5b9d2
Revises: b4d6f8a0c2e1
Create Date: 2026-11-05

The server's own notices used the category ``lifecycle`` (R-1079). They now say what
they are about: FRP notices (``lifecycle.frp.*``) are ``tunnel``, certificate expiry
(``lifecycle.certificate.*``) is ``security``, a deleted server is ``agent``. The upgrade
moves the stored rows by their event_type and rewrites every subscription that filters
on ``lifecycle`` to the three new names, so nobody loses a notice they asked for.

The downgrade maps back: rows whose event_type starts with ``lifecycle.`` become
``lifecycle`` again, and ``tunnel``/``agent`` in a subscription become ``lifecycle``.
That is lossy for subscriptions: one that picked only ``tunnel`` after the upgrade holds
``lifecycle`` after the downgrade and receives the certificate and server notices too.
A subscription whose filter is not a JSON list is left alone: the resolver treats it as
no filter.
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1a7e3f5b9d2"
down_revision: Union[str, Sequence[str], None] = "b4d6f8a0c2e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rewrite_subscriptions(mapping: dict[str, list[str]]) -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, categories FROM notification_subscription WHERE categories IS NOT NULL")
    ).all()
    for sub_id, raw in rows:
        try:
            names = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(names, list) or not any(n in mapping for n in names):
            continue
        rewritten: list = []
        for name in names:
            for new in mapping.get(name, [name]):
                if new not in rewritten:
                    rewritten.append(new)
        conn.execute(
            sa.text("UPDATE notification_subscription SET categories = :c WHERE id = :id"),
            {"c": json.dumps(rewritten), "id": sub_id},
        )


def upgrade() -> None:
    op.execute(
        """
        UPDATE notification SET category = CASE
            WHEN event_type LIKE 'lifecycle.frp.%' THEN 'tunnel'
            WHEN event_type LIKE 'lifecycle.certificate.%' THEN 'security'
            ELSE 'agent'
        END
        WHERE category = 'lifecycle'
        """
    )
    _rewrite_subscriptions({"lifecycle": ["tunnel", "security", "agent"]})


def downgrade() -> None:
    op.execute("UPDATE notification SET category = 'lifecycle' WHERE event_type LIKE 'lifecycle.%'")
    _rewrite_subscriptions({"tunnel": ["lifecycle"], "agent": ["lifecycle"]})
