#!/usr/bin/env python3
"""Generate the performance-lab tables as CSV files.

Two tables, written in parts of --chunk-size rows to data/<table>/part-NNNNN.csv:

    transactions  transaction_id, account_id, amount, transaction_timestamp, status
    user_events   event_id, user_id, event_type, event_timestamp

Accounts and users share one ID space: user N owns account N. That lets later
steps join a user's app activity to their transactions.

Shape of the data, chosen to make performance behave like production:
    Skewed activity   a few heavy accounts and users produce most rows
                      (low IDs are the most active), so some keys have
                      thousands of rows and most have a handful.
    Growth over time  later days have more rows than earlier days.
    Time of day       activity peaks in the afternoon and evening, and is
                      lowest at night.
    Sessions          user_events come in sessions: session_start, a few
                      page views, clicks, searches and cart events, then
                      session_end, seconds to minutes apart.
    Random row order  rows are not stored in time order, as in a real table
                      that receives late and backfilled rows.

Only the standard library is used (random, datetime). Parts are generated in
parallel, each with its own seed, so the output is the same for the same
--seed regardless of --workers.

Usage:
    python scripts/generate_data.py                       # 10M transactions, 20M events
    python scripts/generate_data.py --transactions 100000 --events 200000
"""

import argparse
import csv
import os
import random
import shutil
import time
from bisect import bisect
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from itertools import accumulate
from pathlib import Path

START = datetime(2025, 1, 1)
END = datetime(2026, 11, 1)  # exclusive
TOTAL_DAYS = (END - START).days
END_SECONDS = TOTAL_DAYS * 86_400

# "YYYY-MM-DD" for every day in range. Timestamps are kept as seconds since
# START and formatted with this table, which is much faster than creating a
# datetime object per row.
DAY_STRINGS = [
    (START + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(TOTAL_DAYS)
]

# Higher = more skew toward low account/user IDs. 2.0 gives a long tail where
# the busiest accounts have hundreds of times the median activity.
ACTIVITY_SKEW = 2.0
# Below 1 = more rows on recent days (business growth).
GROWTH_EXPONENT = 0.8

# Relative activity by hour of day (0-23)
HOUR_WEIGHTS = [
    2, 1, 1, 1, 1, 2, 4, 6, 8, 9, 10, 11,
    12, 12, 11, 11, 12, 13, 14, 14, 12, 9, 6, 4,
]  # fmt: skip
HOUR_CUMULATIVE = list(accumulate(HOUR_WEIGHTS))

STATUSES = ["completed", "pending", "failed", "reversed"]
STATUS_CUMULATIVE = list(accumulate([93, 2, 4, 1]))

# Events between session_start and session_end
MID_EVENT_TYPES = ["page_view", "click", "search", "add_to_cart", "checkout"]
MID_EVENT_CUMULATIVE = list(accumulate([45, 30, 12, 9, 4]))

TABLES = {
    "transactions": [
        "transaction_id",
        "account_id",
        "amount",
        "transaction_timestamp",
        "status",
    ],
    "user_events": ["event_id", "user_id", "event_type", "event_timestamp"],
}


def pick(rng: random.Random, options: list, cumulative: list):
    """Weighted choice using a precomputed cumulative weight list."""
    return options[bisect(cumulative, rng.random() * cumulative[-1])]


def skewed_id(rng: random.Random, n_ids: int) -> int:
    """ID between 1 and n_ids, with low IDs much more likely."""
    return 1 + int(n_ids * rng.random() ** ACTIVITY_SKEW)


def random_timestamp(rng: random.Random) -> int:
    """Seconds since START, weighted toward recent days and busy hours."""
    day = int(TOTAL_DAYS * rng.random() ** GROWTH_EXPONENT)
    hour = bisect(HOUR_CUMULATIVE, rng.random() * HOUR_CUMULATIVE[-1])
    return day * 86_400 + hour * 3_600 + rng.randrange(3_600)


def fmt(seconds: int) -> str:
    """Seconds since START -> 'YYYY-MM-DD HH:MM:SS'."""
    day, rest = divmod(seconds, 86_400)
    hour, rest = divmod(rest, 3_600)
    minute, second = divmod(rest, 60)
    return f"{DAY_STRINGS[day]} {hour:02d}:{minute:02d}:{second:02d}"


def write_transactions(path, first_id, n_rows, n_accounts, seed):
    rng = random.Random(seed)
    with open(path, "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(TABLES["transactions"])
        for i in range(n_rows):
            amount = min(rng.lognormvariate(3.4, 1.1), 25_000.0)
            out.writerow(
                [
                    first_id + i,
                    skewed_id(rng, n_accounts),
                    f"{amount:.2f}",
                    fmt(random_timestamp(rng)),
                    pick(rng, STATUSES, STATUS_CUMULATIVE),
                ]
            )
    return n_rows


def write_user_events(path, first_id, n_rows, n_users, seed):
    rng = random.Random(seed)
    written = 0
    with open(path, "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(TABLES["user_events"])
        while written < n_rows:
            user_id = skewed_id(rng, n_users)
            ts = random_timestamp(rng)
            n_middle = rng.randint(1, 12)
            session = (
                ["session_start"]
                + [
                    pick(rng, MID_EVENT_TYPES, MID_EVENT_CUMULATIVE)
                    for _ in range(n_middle)
                ]
                + ["session_end"]
            )
            for event_type in session:
                # Cut a session short at the end of a part or of the date range
                if written == n_rows or ts >= END_SECONDS:
                    break
                out.writerow([first_id + written, user_id, event_type, fmt(ts)])
                written += 1
                ts += rng.randint(2, 180)
    return written


def generate_part(task):
    table, path, first_id, n_rows, n_ids, seed = task
    writer = write_transactions if table == "transactions" else write_user_events
    return table, writer(path, first_id, n_rows, n_ids, seed)


def plan_tasks(table, total_rows, chunk_size, n_ids, seed, out_dir):
    """Split a table into parts. Each part gets its own seed and ID range."""
    table_dir = out_dir / table
    if table_dir.exists():
        shutil.rmtree(table_dir)  # never mix parts from different runs
    table_dir.mkdir(parents=True)
    table_seed = seed * 1_000 + (1 if table == "transactions" else 2)
    tasks = []
    for part, first_row in enumerate(range(0, total_rows, chunk_size)):
        n_rows = min(chunk_size, total_rows - first_row)
        path = table_dir / f"part-{part:05d}.csv"
        tasks.append(
            (table, path, first_row + 1, n_rows, n_ids, table_seed * 100_000 + part)
        )
    return tasks


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--transactions", type=int, default=10_000_000)
    parser.add_argument("--events", type=int, default=20_000_000)
    parser.add_argument(
        "--accounts", type=int, default=500_000, help="also the number of users"
    )
    parser.add_argument(
        "--chunk-size", type=int, default=1_000_000, help="rows per CSV part"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    parser.add_argument("--out-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    tasks = plan_tasks(
        "transactions",
        args.transactions,
        args.chunk_size,
        args.accounts,
        args.seed,
        args.out_dir,
    ) + plan_tasks(
        "user_events",
        args.events,
        args.chunk_size,
        args.accounts,
        args.seed,
        args.out_dir,
    )

    started = time.perf_counter()
    totals = {"transactions": 0, "user_events": 0}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for table, n_rows in pool.map(generate_part, tasks):
            totals[table] += n_rows

    elapsed = time.perf_counter() - started
    for table, n_rows in totals.items():
        size_mb = (
            sum(p.stat().st_size for p in (args.out_dir / table).glob("*.csv")) / 1e6
        )
        print(
            f"{table:13s} {n_rows:>12,} rows  {size_mb:>8,.0f} MB  in {args.out_dir / table}/"
        )
    print(f"Done in {elapsed:.0f}s with {args.workers} workers.")


if __name__ == "__main__":
    main()
