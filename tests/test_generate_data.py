"""Small end-to-end run of the data generator."""

import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_generator(out_dir, workers):
    subprocess.run(
        [
            sys.executable, str(ROOT / "scripts/generate_data.py"),
            "--transactions", "5000", "--events", "8000", "--accounts", "300",
            "--chunk-size", "2000", "--workers", str(workers), "--out-dir", str(out_dir),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip


def read_table(out_dir, table):
    rows = []
    for part in sorted((out_dir / table).glob("part-*.csv")):
        with open(part) as f:
            rows.extend(csv.DictReader(f))
    return rows


def test_row_counts_ids_and_values(tmp_path):
    run_generator(tmp_path, workers=2)
    txns = read_table(tmp_path, "transactions")
    events = read_table(tmp_path, "user_events")

    assert len(txns) == 5000
    assert len(events) == 8000
    # IDs are unique and consecutive across parts
    assert [int(r["transaction_id"]) for r in txns] == list(range(1, 5001))
    assert [int(r["event_id"]) for r in events] == list(range(1, 8001))
    # Values are in range
    assert all(1 <= int(r["account_id"]) <= 300 for r in txns)
    assert all(float(r["amount"]) > 0 for r in txns)
    assert {r["status"] for r in txns} <= {"completed", "pending", "failed", "reversed"}
    assert all("2025-01-01" <= r["transaction_timestamp"] < "2026-11-01" for r in txns)
    assert all("2025-01-01" <= r["event_timestamp"] < "2026-11-01" for r in events)


def test_same_seed_same_output_with_any_worker_count(tmp_path):
    run_generator(tmp_path / "a", workers=1)
    run_generator(tmp_path / "b", workers=4)
    for table in ("transactions", "user_events"):
        assert read_table(tmp_path / "a", table) == read_table(tmp_path / "b", table)
