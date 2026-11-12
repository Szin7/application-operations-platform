import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import URL, create_engine, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

project_root = Path(__file__).resolve().parents[1]
settings = {
    **dotenv_values(project_root / ".env", interpolate=False),
    **os.environ,
}

target_metadata = None


def run_migrations_offline():
    context.configure(
        dialect_name="postgresql",
        literal_binds=True,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    required = (
        "APP_DB_HOST",
        "APP_DB_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    if any(not settings.get(key) for key in required):
        raise ValueError("Missing migration database configuration")

    database_url = URL.create(
        drivername="postgresql+psycopg",
        username=settings["POSTGRES_USER"],
        password=settings["POSTGRES_PASSWORD"],
        host=settings["APP_DB_HOST"],
        port=int(settings["APP_DB_PORT"]),
        database=settings["POSTGRES_DB"],
    )

    engine = create_engine(
        database_url,
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 5},
    )

    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
