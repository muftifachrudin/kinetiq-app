import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from kinetiq_db.engine import normalize_db_url
from kinetiq_db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL_MIGRATIONS (Fase 0d, docs/sonnet5-implementation-roadmap.md):
# migrations run DDL (CREATE/ALTER/DROP), which the app's own runtime role
# is meant to NOT have once it's switched to the least-privilege kinetiq_app
# role (migration 0006) -- so this reads a SEPARATE, owner-role connection
# string reserved just for this alembic step, when one is configured.
# Falls back to plain DATABASE_URL when DATABASE_URL_MIGRATIONS isn't set
# -- local dev, CI's neon-preview-branch job, and any environment that
# hasn't done the Fase 0d role switch yet all only ever set DATABASE_URL,
# and in every one of those there's only a single role in play anyway, so
# this fallback is a no-op change in behavior for all of them. Neither is
# ever hardcoded/committed.
db_url = os.environ.get("DATABASE_URL_MIGRATIONS") or os.environ.get("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", normalize_db_url(db_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
