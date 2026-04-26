# backend/alembic/env.py
# Alembic migration environment — connects your models to the DB for autogeneration.
# The key change from the default: we import Base and all models so Alembic
# can diff them against the live DB schema and generate accurate migrations.

from app.core.database import Base
from app.core.config import settings
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import sys
import os

# Add backend/ to Python path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# CRITICAL: import all models here so Alembic sees them in Base.metadata
# If you add a new model file later, import it here too
import app.models.models  # noqa: F401 — side-effect import registers models with Base

config = context.config

# Use our DATABASE_URL from .env instead of alembic.ini
# This means you only manage the connection string in one place
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection — generates SQL scripts."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live Neon DB — what you'll use 99% of the time."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool = no connection pooling in migrations
        # Avoids issues with Neon's serverless connection limits
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
