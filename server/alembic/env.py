"""Alembic env.py — liest DATABASE_URL aus app.core.config, importiert alle
Models, damit autogenerate die volle Base.metadata sieht."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# App-Imports — muessen vor target_metadata stehen, damit Base.metadata
# alle Tabellen kennt.
from app.core.config import DATABASE_URL
from app.core.database import Base

# Alle Module mit __tablename__ explizit importieren, sonst fehlen sie
# in Base.metadata fuer autogenerate.
import app.modules.users.models  # noqa: F401
import app.modules.servers.models  # noqa: F401
import app.modules.connections.models  # noqa: F401
import app.modules.api_keys.models  # noqa: F401
import app.modules.hooks.models  # noqa: F401
import app.modules.frp.models  # noqa: F401
import app.modules.ansible.models  # noqa: F401

# Alembic-Config-Objekt
config = context.config

# DATABASE_URL aus app-config setzen (ueberschreibt sqlalchemy.url aus alembic.ini)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Offline-Modus: nur URL, kein Engine. Generiert SQL-Skript."""
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
    """Online-Modus: echte Engine, fuehrt Migrationen direkt aus."""
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
