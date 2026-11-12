import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def get_connection() -> psycopg.Connection:
    config = {
        **dotenv_values(ENV_FILE, interpolate=False),
        **os.environ,
    }
    required = (
        "APP_DB_HOST",
        "APP_DB_PORT",
        "APP_DB_NAME",
        "APP_DB_USER",
        "APP_DB_PASSWORD",
    )
    if any(not config.get(key) for key in required):
        raise ValueError("Missing database configuration")

    return psycopg.connect(
        host=config["APP_DB_HOST"],
        port=int(config["APP_DB_PORT"]),
        dbname=config["APP_DB_NAME"],
        user=config["APP_DB_USER"],
        password=config["APP_DB_PASSWORD"],
        connect_timeout=3,
        options="-c statement_timeout=3000",
    )


def check_database() -> None:
    with get_connection() as connection:
        connection.execute("SELECT 1").fetchone()
