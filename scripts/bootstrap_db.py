"""Prepare the application database role, schema, and permissions."""

import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main():
    settings = {
        **dotenv_values(PROJECT_ROOT / ".env", interpolate=False),
        **os.environ,
    }
    required = (
        "APP_DB_HOST",
        "APP_DB_PORT",
        "APP_DB_NAME",
        "APP_DB_USER",
        "APP_DB_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    if any(not settings.get(key) for key in required):
        raise ValueError("Missing database bootstrap configuration")

    if settings["APP_DB_NAME"] != settings["POSTGRES_DB"]:
        raise ValueError("Application and administrator database names differ")

    if settings["APP_DB_USER"] == settings["POSTGRES_USER"]:
        raise ValueError("Application and administrator roles must differ")

    connection_options = {
        "host": settings["APP_DB_HOST"],
        "port": int(settings["APP_DB_PORT"]),
        "dbname": settings["POSTGRES_DB"],
        "connect_timeout": 5,
    }
    identifiers = {
        "app_role": sql.Identifier(settings["APP_DB_USER"]),
        "admin_role": sql.Identifier(settings["POSTGRES_USER"]),
        "database": sql.Identifier(settings["POSTGRES_DB"]),
    }

    with psycopg.connect(
        **connection_options,
        user=settings["POSTGRES_USER"],
        password=settings["POSTGRES_PASSWORD"],
    ) as connection:
        role = connection.execute(
            """
            SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                   rolreplication, rolbypassrls
            FROM pg_roles
            WHERE rolname = %s
            """,
            (settings["APP_DB_USER"],),
        ).fetchone()

        if role is None:
            connection.execute(
                sql.SQL(
                    """
                    CREATE ROLE {app_role}
                    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOREPLICATION NOBYPASSRLS PASSWORD {password}
                    """
                ).format(
                    app_role=identifiers["app_role"],
                    password=sql.Literal(settings["APP_DB_PASSWORD"]),
                )
            )
        elif not role[0] or any(role[1:]):
            raise ValueError("Existing application role has unexpected attributes")

        statements = (
            "CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION {admin_role}",
            "REVOKE CREATE ON SCHEMA app FROM PUBLIC, {app_role}",
            "GRANT CONNECT ON DATABASE {database} TO {app_role}",
            "GRANT USAGE ON SCHEMA app TO {app_role}",
            """
            GRANT SELECT, INSERT, UPDATE, DELETE
            ON ALL TABLES IN SCHEMA app TO {app_role}
            """,
            "GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO {app_role}",
            """
            ALTER DEFAULT PRIVILEGES FOR ROLE {admin_role} IN SCHEMA app
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role}
            """,
            """
            ALTER DEFAULT PRIVILEGES FOR ROLE {admin_role} IN SCHEMA app
            GRANT USAGE ON SEQUENCES TO {app_role}
            """,
        )
        for statement in statements:
            connection.execute(sql.SQL(statement).format(**identifiers))

    with psycopg.connect(
        **connection_options,
        user=settings["APP_DB_USER"],
        password=settings["APP_DB_PASSWORD"],
    ) as connection:
        database, username = connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone()
        if (database, username) != (
            settings["APP_DB_NAME"],
            settings["APP_DB_USER"],
        ):
            raise ValueError("Application connected with an unexpected identity")

    print("Database bootstrap completed.")
    print("Application login verified.")


if __name__ == "__main__":
    main()
