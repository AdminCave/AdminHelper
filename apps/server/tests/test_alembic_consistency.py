# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drift detector: ensures that alembic/versions/ and Base.metadata are
in sync. Fails if someone changes a model without generating a new
Alembic migration (or vice versa).

Implementation: uses the pattern behind 'alembic check' --
autogenerate diff against the live DB."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.core.database import Base


def test_alembic_migrations_match_models(pg_engine):
    """Compares Base.metadata against the live Postgres schema (created via
    conftest's pg_engine through Base.metadata.create_all).

    Catches the more interesting case where someone adds a column to a model
    but forgets 'alembic revision --autogenerate': the next CI run that applies
    Alembic fresh against an empty DB then fails later in the real deployment
    path."""
    with pg_engine.connect() as conn:
        ctx = MigrationContext.configure(connection=conn)
        diffs = compare_metadata(ctx, Base.metadata)

    assert not diffs, (
        "Alembic ist out-of-sync mit Base.metadata. Auto-generate eine neue "
        "Migration mit:\n"
        "    alembic revision --autogenerate -m 'beschreibender name'\n\n"
        f"Diffs: {diffs}"
    )
