# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Alembic env.py — reads DATABASE_URL from app.core.config and imports all
models so autogenerate sees the full Base.metadata."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

import app.modules.ansible.models  # noqa: F401
import app.modules.api_keys.models  # noqa: F401
import app.modules.audit.models  # noqa: F401
import app.modules.connections.models  # noqa: F401
import app.modules.enrollment.models  # noqa: F401
import app.modules.frp.models  # noqa: F401
import app.modules.hooks.models  # noqa: F401
import app.modules.notifications.models  # noqa: F401
import app.modules.provisioning.models  # noqa: F401
import app.modules.servers.models  # noqa: F401

# Explicitly import all modules with __tablename__, otherwise they are
# missing from Base.metadata for autogenerate.
import app.modules.users.models  # noqa: F401

# App imports — must come before target_metadata so Base.metadata
# knows about all tables.
from app.core.config import DATABASE_URL
from app.core.database import Base

# Alembic config object
config = context.config

# Set DATABASE_URL from app config (overrides sqlalchemy.url from alembic.ini)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Advisory-lock key for the migration run. DISTINCT from monitoring's (0xAD314C): both services
# share one Postgres cluster (separate DBs) and advisory locks are cluster-wide, so a shared key
# would needlessly serialize server vs monitoring migrations.
_MIGRATION_LOCK = 0xAD314B


def run_migrations_offline() -> None:
    """Offline mode: URL only, no engine. Generates a SQL script."""
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
    """Online mode: real engine, runs migrations directly."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Serialize concurrent migration runs (docker compose up --scale server=2, a rolling
        # update): only the scheduler is pinned to one replica, not the server. A session-level
        # advisory lock makes the second starter block here until the first releases it, instead
        # of both reading the same alembic_version and racing into a DuplicateTable/unique
        # violation. commit() ends the autobegun transaction so Alembic owns its own; the
        # session-level lock survives it and is released explicitly in finally — reliably even for
        # a no-op run, and it also guards non-transactional steps a per-migration transaction
        # wouldn't (4.61).
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
