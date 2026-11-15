#!/usr/bin/env python3
"""Prove that optimized queries return exactly what the originals return.

Each group lists queries that must produce identical rows: the slow baseline
and its rewrites, or the same query run on different storage layouts. Every
query in a group is run, its rows are checksummed (same checksum as
scripts/benchmark.py), and the script fails if any checksum differs.

Queries in RUN_ONLY have nothing to compare against; they only have to run
without errors.

Needs the tables from scripts/load_data.py and the storage layouts from
sql/storage/*.sql. CI runs this on a small dataset on every pull request.

Usage:
    python scripts/check_equivalence.py [--report-days 7]
"""

import argparse
import sys
import time
from pathlib import Path

from benchmark import checksum, render
from db import connect

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "sql/queries"

# Queries in the same group must return identical rows.
EQUIVALENT_GROUPS = {
    "rolling 30-day metrics (Step 1 baseline vs Step 5 rewrites)": [
        "01_baseline_rolling_30d",
        "05a_rolling_30d_ctes",
        "05b_rolling_30d_window",
    ],
    "week range filter (Step 4 storage layouts)": [
        "04_week_range_original",
        "04_week_range_partitioned",
        "04_week_range_time_sorted_brin",
    ],
    "account history lookup (Step 4 storage layouts)": [
        "04_account_history_original",
        "04_account_history_clustered",
    ],
    "CTE materialized vs inlined (Step 5)": [
        "05c_cte_materialized",
        "05d_cte_inlined",
    ],
}

# Queries with no counterpart: they only need to run.
RUN_ONLY = ["03a_sessionize_events", "03b_running_balance"]


def run(cur, name: str, report_days: int) -> tuple[str, int, float]:
    sql = render((QUERIES / f"{name}.sql").read_text(), report_days)
    started = time.perf_counter()
    cur.execute(sql)
    rows = cur.fetchall()
    return checksum(rows), len(rows), time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--report-days", type=int, default=7)
    args = parser.parse_args()

    failures = []
    with connect() as conn, conn.cursor() as cur:
        for group, names in EQUIVALENT_GROUPS.items():
            print(f"\n{group}")
            results = {name: run(cur, name, args.report_days) for name in names}
            reference = results[names[0]][0]
            for name, (digest, n_rows, seconds) in results.items():
                same = digest == reference
                mark = "ok  " if same else "DIFF"
                print(
                    f"  {mark} {name:34s} {n_rows:>8,} rows  {seconds:7.2f}s  {digest[:12]}"
                )
                if not same:
                    failures.append(f"{name} differs from {names[0]}")
            if results[names[0]][1] == 0:
                failures.append(f"{group}: reference query returned no rows")

        print("\nrun only")
        for name in RUN_ONLY:
            _, n_rows, seconds = run(cur, name, args.report_days)
            print(f"  ran  {name:34s} {n_rows:>8,} rows  {seconds:7.2f}s")

    if failures:
        print("\nFAILED:\n  " + "\n  ".join(failures))
        return 1
    print("\nAll equivalent queries returned identical results.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
