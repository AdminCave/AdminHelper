"""Alembic env.py — liest DATABASE_URL aus app.core.config, importiert alle
Models, damit autogenerate die volle Base.metadata sieht."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# App-Imports — muessen vor target_metadata stehen.
from app.core.config import DATABASE_URL
from app.core.database import Base

# Alle Tabellen werden in app/models.py definiert — ein einziger Import reicht.
import app.models  # noqa: F401

config = context.config

# DATABASE_URL aus app-config setzen (ueberschreibt sqlalchemy.url aus alembic.ini)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
