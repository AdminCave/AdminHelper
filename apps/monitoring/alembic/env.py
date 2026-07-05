# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Alembic env.py — reads DATABASE_URL from app.core.config, imports all
models so autogenerate sees the full Base.metadata."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# All tables are defined in app/models.py — a single import is enough.
import app.models  # noqa: F401

# App imports — must come before target_metadata.
from app.core.config import DATABASE_URL
from app.core.database import Base

config = context.config

# Set DATABASE_URL from app config (overrides sqlalchemy.url from alembic.ini)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Advisory-lock key for the migration run. DISTINCT from the server's (0xAD314B): both services
# share one Postgres cluster (separate DBs adminhelper / adminhelper_monitor) and advisory locks
# are cluster-wide, so a shared key would needlessly serialize server vs monitoring migrations.
_MIGRATION_LOCK = 0xAD314C


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Serialize concurrent migration runs (scaled replicas / rolling update): a session-level
        # advisory lock makes the second starter block here until the first releases it, instead
        # of both reading the same alembic_version and racing into a DuplicateTable/unique
        # violation. commit() ends the autobegun transaction so Alembic owns its own; the
        # session-level lock survives it and is released explicitly in finally — reliably even for
        # a no-op run (4.61).
        connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _MIGRATION_LOCK})
        connection.commit()
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
            )

            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _MIGRATION_LOCK})
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
