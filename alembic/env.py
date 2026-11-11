"""Alembic environment (async). Reads the DB URL and model metadata straight from the application."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401  (imports every model so autogenerate sees all tables)
from alembic import context
from app.core.config import settings
from app.core.database import Base

config = context.config

# Keep the app's structlog config intact when migrations are run programmatically (e.g. from tests).
if config.config_file_name is not None and not config.attributes.get("skip_logging_config", False):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    # An explicit `-x`/set_main_option URL wins (used by tests); otherwise use the app settings.
    return config.get_main_option("sqlalchemy.url") or settings.DATABASE_URL


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting:  alembic upgrade head --sql"""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # SQLite cannot ALTER most things in place; batch mode recreates the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
