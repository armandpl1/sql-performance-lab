#!/usr/bin/env python3
"""Load the generated CSV parts into PostgreSQL.

Steps:
    1. Recreate the tables (sql/schema.sql), without indexes.
    2. Stream every CSV part in with COPY.
    3. Add the baseline indexes (sql/indexes.sql). Building indexes after the
       load is much faster than updating them row by row during it.
    4. VACUUM ANALYZE, so the planner has fresh statistics and index-only
       scans can use the visibility map.

Usage:
    python scripts/load_data.py [--data-dir data]
"""

import argparse
import time
from contextlib import contextmanager
from pathlib import Path

from db import connect

ROOT = Path(__file__).resolve().parent.parent
TABLES = ["transactions", "user_events"]


@contextmanager
def timed(label):
    """Print how long a block took."""
    print(f"{label} ...", flush=True)
    start = time.perf_counter()
    yield
    print(f"{label} done in {time.perf_counter() - start:.1f}s", flush=True)


def copy_table(cur, table, data_dir):
    parts = sorted((data_dir / table).glob("part-*.csv"))
    if not parts:
        raise SystemExit(
            f"No CSV parts in {data_dir / table}. Run scripts/generate_data.py first."
        )
    for part in parts:
        with (
            open(part, "rb") as f,
            cur.copy(f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true)") as copy,
        ):
            while chunk := f.read(1 << 20):
                copy.write(chunk)
    return len(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()

    with connect(autocommit=True) as conn, conn.cursor() as cur:
        with timed("Creating tables"):
            cur.execute((ROOT / "sql/schema.sql").read_text())

        for table in TABLES:
            with timed(f"Loading {table}"):
                n_parts = copy_table(cur, table, args.data_dir)
                print(f"  {n_parts} parts")

        with timed("Creating baseline indexes"):
            cur.execute((ROOT / "sql/indexes.sql").read_text())

        with timed("VACUUM ANALYZE"):
            for table in TABLES:
                cur.execute(f"VACUUM ANALYZE {table}")

        print()
        for table in TABLES:
            cur.execute(
                f"SELECT count(*), pg_size_pretty(pg_table_size('{table}')),"
                f" pg_size_pretty(pg_indexes_size('{table}')) FROM {table}"
            )
            rows, table_size, index_size = cur.fetchone()
            print(
                f"{table:13s} {rows:>12,} rows  table {table_size:>8}  indexes {index_size:>8}"
            )


if __name__ == "__main__":
    main()
