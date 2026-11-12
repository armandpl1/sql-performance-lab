#!/usr/bin/env python3
"""Run a SQL file statement by statement, and report how long each took.

Statements are split with PostgreSQL's own parser (pglast) and run one at a
time in autocommit mode, because some commands (VACUUM, CREATE INDEX
CONCURRENTLY) refuse to run inside a multi-statement batch.

Usage:
    python scripts/run_sql.py sql/storage/04a_partition_by_month.sql
"""

import sys
import time
from pathlib import Path

from db import connect
from pglast import split


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    total = time.perf_counter()
    with connect(autocommit=True) as conn:
        for statement in split(path.read_text()):
            started = time.perf_counter()
            conn.execute(statement)
            first_line = " ".join(statement.split())[:70]
            print(f"  {time.perf_counter() - started:7.1f}s  {first_line}", flush=True)
    print(f"{path.name}: done in {time.perf_counter() - total:.1f}s")


if __name__ == "__main__":
    main()
