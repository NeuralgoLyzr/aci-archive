import asyncio
import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from aci.common.db.sql_models import Base
from aci.common.utils import (
    _build_iam_sqlalchemy_url,
    _iam_auth_enabled,
    attach_iam_token_provider,
)

load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def _get_db_password() -> str:
    """Fetches the DB password via cloudrift secrets."""
    from aci.common.utils import _fetch_db_password

    secret_name = os.getenv("DB_SECRET_NAME")
    if not secret_name:
        return os.getenv("SERVER_DB_PASSWORD", "")
    return asyncio.run(_fetch_db_password(secret_name))


def _get_db_url() -> str:
    # construct db url from env variables - try ALEMBIC_* first, fallback to SERVER_*
    DB_SCHEME = os.getenv("ALEMBIC_DB_SCHEME") or os.getenv("SERVER_DB_SCHEME") or "postgresql+psycopg"
    DB_USER = os.getenv("ALEMBIC_DB_USER") or os.getenv("SERVER_DB_USER") or "postgres"
    DB_HOST = os.getenv("ALEMBIC_DB_HOST") or os.getenv("SERVER_DB_HOST") or "localhost"
    DB_PORT = os.getenv("ALEMBIC_DB_PORT") or os.getenv("SERVER_DB_PORT") or "5432"
    DB_NAME = os.getenv("ALEMBIC_DB_NAME") or os.getenv("SERVER_DB_NAME") or "my_app_db"
    if _iam_auth_enabled():
        # IAM token is minted per-connection by attach_iam_token_provider, so the
        # URL carries no password.
        return _build_iam_sqlalchemy_url(DB_SCHEME, DB_USER, DB_HOST, DB_PORT, DB_NAME)
    DB_PASSWORD = _get_db_password()
    return f"{DB_SCHEME}://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=_get_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_db_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    if _iam_auth_enabled():
        attach_iam_token_provider(connectable)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
