"""Drift-Detektor: stellt sicher, dass alembic/versions/ und Base.metadata
synchron sind. Schlaegt fehl, wenn jemand ein Model aendert ohne eine neue
Alembic-Migration zu generieren (oder umgekehrt).

Implementierung: nutzt das Pattern hinter 'alembic check' --
autogenerate-Diff gegen die Live-DB."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.core.database import Base


def test_alembic_migrations_match_models(pg_engine):
    """Vergleicht Base.metadata gegen die Live-Postgres-Schema (die per
    conftest's pg_engine via Base.metadata.create_all entsteht).

    Faengt den interessanteren Fall, wo jemand eine Column zu einem Model
    hinzufuegt aber 'alembic revision --autogenerate' vergisst: der naechste
    CI-Run, der Alembic frisch gegen eine leere DB anwendet, scheitert dann
    spaeter im realen Deployment-Pfad."""
    with pg_engine.connect() as conn:
        ctx = MigrationContext.configure(connection=conn)
        diffs = compare_metadata(ctx, Base.metadata)

    assert not diffs, (
        "Alembic ist out-of-sync mit Base.metadata. Auto-generate eine neue "
        "Migration mit:\n"
        "    alembic revision --autogenerate -m 'beschreibender name'\n\n"
        f"Diffs: {diffs}"
    )
