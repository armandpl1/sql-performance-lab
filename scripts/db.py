"""Shared database connection settings.

Defaults match docker-compose.yml. Override with the standard PostgreSQL
environment variables (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE).
"""

import os

import psycopg


def connect(**kwargs) -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        user=os.getenv("PGUSER", "lab"),
        password=os.getenv("PGPASSWORD", "lab"),
        dbname=os.getenv("PGDATABASE", "lab"),
        **kwargs,
    )
