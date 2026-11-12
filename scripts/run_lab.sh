#!/usr/bin/env bash
# Run every step of the lab in order. Results go to results/.
# Assumes PostgreSQL is up (docker compose up -d) and data/ is generated.
# Set SKIP_LOAD=1 to reuse already-loaded tables.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="uv run python"

if [[ "${SKIP_LOAD:-0}" != "1" ]]; then
  echo "== Load"
  $PY scripts/load_data.py
fi

echo "== Step 1-2: baseline, timed and diagnosed"
$PY scripts/benchmark.py sql/queries/01_baseline_rolling_30d.sql --runs 1 --no-explain --label baseline
$PY scripts/analyze_plan.py sql/queries/01_baseline_rolling_30d.sql

echo "== Step 3: window functions"
for q in 03a_sessionize_events 03b_running_balance; do
  $PY scripts/benchmark.py sql/queries/$q.sql --runs 3 --no-explain
  $PY scripts/analyze_plan.py sql/queries/$q.sql
done

echo "== Step 4: storage layouts"
for f in sql/storage/04*.sql; do $PY scripts/run_sql.py "$f"; done
for q in sql/queries/04_*.sql; do
  $PY scripts/benchmark.py "$q" --runs 5 --no-explain
  $PY scripts/analyze_plan.py "$q"
done

echo "== Step 5: rewrites (checksums must match the baseline)"
for q in 05a_rolling_30d_ctes 05b_rolling_30d_window 05c_cte_materialized 05d_cte_inlined; do
  $PY scripts/benchmark.py sql/queries/$q.sql --runs 3 --no-explain
  $PY scripts/analyze_plan.py sql/queries/$q.sql
done

echo "== Done. See results/benchmarks.csv and results/analysis/"
