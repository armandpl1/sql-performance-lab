#!/usr/bin/env python3
"""Time a query file against PostgreSQL and save its execution plan.

For a query file sql/queries/<name>.sql this:
    1. Runs EXPLAIN (ANALYZE, BUFFERS, SETTINGS) once and saves the plan to
       results/plans/<name>.txt.
    2. Runs the query --runs times, fetching every row, and records the
       wall-clock time of each run.
    3. Computes a checksum of the result rows, so a faster rewrite can be
       proven to return exactly the same answer.
    4. Appends a line to results/benchmarks.csv.

EXPLAIN ANALYZE adds timing overhead to every plan node, so its total time
is higher than the measured runs. Use the measured runs for comparisons and
the plan to see where the time goes.

The first run reads data from disk into cache; later runs are usually faster.
The median of all runs is reported, along with the minimum and maximum.

Usage:
    python scripts/benchmark.py sql/queries/01_baseline_rolling_30d.sql
    python scripts/benchmark.py sql/queries/01_baseline_rolling_30d.sql --runs 1 --report-days 30
"""

import argparse
import csv
import hashlib
import statistics
import time
from datetime import datetime
from pathlib import Path

from db import connect

ROOT = Path(__file__).resolve().parent.parent
RESULTS_CSV = ROOT / "results/benchmarks.csv"
PLANS_DIR = ROOT / "results/plans"


def render(sql: str, report_days: int) -> str:
    """Fill in :report_days. Plain substitution so the same file runs in psql."""
    return sql.replace(":report_days", str(int(report_days)))


def checksum(rows) -> str:
    """MD5 of the result rows in the order returned (queries end with ORDER BY)."""
    digest = hashlib.md5()
    for row in rows:
        digest.update(
            ("|".join("" if v is None else str(v) for v in row) + "\n").encode()
        )
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("query_file", type=Path)
    parser.add_argument("--runs", type=int, default=3, help="timed runs (default 3)")
    parser.add_argument(
        "--report-days", type=int, default=7, help="days of output (default 7)"
    )
    parser.add_argument(
        "--timeout-min",
        type=float,
        default=60,
        help="cancel any run after this many minutes",
    )
    parser.add_argument(
        "--no-explain", action="store_true", help="skip EXPLAIN ANALYZE"
    )
    parser.add_argument(
        "--label", default="", help="free-text note saved with the result"
    )
    args = parser.parse_args()

    name = args.query_file.stem
    sql = render(args.query_file.read_text(), args.report_days)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = '{int(args.timeout_min * 60_000)}ms'")
        cur.execute("SHOW server_version")
        pg_version = cur.fetchone()[0].split()[0]

        if not args.no_explain:
            print(f"EXPLAIN ANALYZE {name} ...", flush=True)
            started = time.perf_counter()
            cur.execute("EXPLAIN (ANALYZE, BUFFERS, SETTINGS) " + sql)
            plan = "\n".join(row[0] for row in cur.fetchall())
            explain_s = time.perf_counter() - started
            PLANS_DIR.mkdir(parents=True, exist_ok=True)
            header = (
                f"-- {name}  report_days={args.report_days}  PostgreSQL {pg_version}\n"
                f"-- captured {datetime.now():%Y-%m-%d %H:%M}, "
                f"EXPLAIN ANALYZE wall time {explain_s:.1f}s\n\n"
            )
            (PLANS_DIR / f"{name}.txt").write_text(header + plan + "\n")
            print(f"  plan saved to {(PLANS_DIR / f'{name}.txt').relative_to(ROOT)}")

        timings, result_rows = [], None
        for run in range(1, args.runs + 1):
            started = time.perf_counter()
            cur.execute(sql)
            result_rows = cur.fetchall()
            timings.append(time.perf_counter() - started)
            print(
                f"  run {run}: {timings[-1]:.2f}s ({len(result_rows):,} rows)",
                flush=True,
            )

    result = {
        "run_at": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "query": name,
        "report_days": args.report_days,
        "runs": args.runs,
        "median_s": round(statistics.median(timings), 3),
        "min_s": round(min(timings), 3),
        "max_s": round(max(timings), 3),
        "rows": len(result_rows),
        "checksum": checksum(result_rows),
        "postgres": pg_version,
        "label": args.label,
    }
    new_file = not RESULTS_CSV.exists()
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=result.keys())
        if new_file:
            writer.writeheader()
        writer.writerow(result)

    print(
        f"\n{name}: median {result['median_s']}s over {args.runs} run(s), "
        f"{result['rows']:,} rows, checksum {result['checksum'][:12]}"
    )
    print(f"Saved to {RESULTS_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
