# SQL Performance Lab

Measuring and fixing slow analytical SQL on PostgreSQL, at a scale where it matters: 10 million transactions and 20 million app events.

Each step starts from a measured baseline, changes one thing, and records:
- the new run time
- the execution plan (`EXPLAIN ANALYZE`)
- a checksum that proves the result didn't change

## Quick start

Requires Docker, Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
make install       # Python dependencies from uv.lock
make hooks         # once: run lint checks before every commit
make db-up         # PostgreSQL 17 on localhost:5432 (waits until healthy)
make data          # 10M transactions + 20M events as CSV (~2 min)
make load          # load into PostgreSQL and build baseline indexes
make lab           # run every step at full scale: timings, plans, reports
```

Quick correctness check on a small dataset (what CI runs): `make integration`.
Run `make help` for every command.

Connection settings default to the Docker container (`lab` / `lab` on `localhost:5432`). Override them with the standard `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` and `PGDATABASE` variables.

## Step 1: Performance lab and baseline

### Database

PostgreSQL 17 runs in Docker (`docker-compose.yml`) with settings sized for a laptop with about 8 GB of RAM:

| Setting                           | Value | Why                                                                |
| --------------------------------- | ----- | ------------------------------------------------------------------ |
| `shared_buffers`                  | 1GB   | PostgreSQL's own cache                                             |
| `effective_cache_size`            | 3GB   | Tells the planner how much the OS is likely caching                |
| `work_mem`                        | 64MB  | Memory per sort or hash before spilling to disk                    |
| `max_parallel_workers_per_gather` | 4     | Parallel scans and aggregates                                      |
| `track_io_timing`                 | on    | Shows I/O time in `EXPLAIN (ANALYZE, BUFFERS)`                     |
| `shm_size` (Docker)               | 1gb   | Parallel query needs more shared memory than Docker's 64MB default |

Every saved plan includes the settings it ran with (`EXPLAIN ... SETTINGS`).

### Data

`scripts/generate_data.py` writes both tables as CSV using only Python's `random` and `datetime`. It generates parts in parallel with one seed per part, so the same `--seed` always gives the same files, whatever the number of workers.

| Table          | Rows       | Columns                                                                     |
| -------------- | ---------- | --------------------------------------------------------------------------- |
| `transactions` | 10,000,000 | `transaction_id`, `account_id`, `amount`, `transaction_timestamp`, `status` |
| `user_events`  | 20,000,000 | `event_id`, `user_id`, `event_type`, `event_timestamp`                      |

The data is shaped to make performance behave as it does in production:

- **Skewed activity.** 500,000 accounts, where low IDs are far more active. The median account has about 20 transactions; the busiest has over 10,000. Skew is what turns "re-read the account's history for each row" into a real problem.
- **Growth over time.** From 2025-01-01 to 2026-10-31, with each quarter busier than the last.
- **Time of day.** Activity peaks in the afternoon and evening.
- **Realistic values.**
  - Amounts follow a log-normal distribution (median about $30).
  - Statuses are 93% completed, 4% failed, 2% pending and 1% reversed.
- **Sessions.** `user_events` come in sessions: `session_start`, then page views, clicks, searches and cart events seconds to minutes apart, then `session_end`.
- **Shared IDs.** User N owns account N, so app activity can be joined to transactions.
- **Unordered storage.** Rows are not stored in time order, as in a real table that receives late and backfilled rows.

### Schema and baseline indexes

`sql/schema.sql` creates the tables. `sql/indexes.sql` adds the indexes a typical team would add by default after the load:

| Table          | Indexes                                                |
| -------------- | ------------------------------------------------------ |
| `transactions` | primary key, `(account_id)`, `(transaction_timestamp)` |
| `user_events`  | primary key, `(user_id)`, `(event_timestamp)`          |

### The baseline query

`sql/queries/01_baseline_rolling_30d.sql` computes **rolling 30-day account metrics**. It returns one row per account per day with activity, for the last `report_days` days of data (default 7). Each row covers the 30 days ending on that day:
- completed transaction count and amount
- average completed amount
- failed transaction count
- app event count

It is deliberately written badly, in four common ways:

| #   | Anti-pattern                                                     | Cost                                                                                                                                        |
| --- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Five correlated subqueries**                                   | Each runs once per transaction in the window and re-reads the account's entire history. A busy account's history is read hundreds of times. |
| 2   | **Functions on indexed columns** (`DATE(transaction_timestamp)`) | The timestamp indexes can't be used, so the window filter scans the whole table and every subquery checks the account's rows one by one.    |
| 3   | **Compute per row, then `DISTINCT`**                             | Metrics are computed for every transaction, then collapsed to account-days, which also means sorting every result.                          |
| 4   | **`MAX(DATE(...))`**                                             | Reads all 10M rows, where `MAX(transaction_timestamp)` could read one index entry.                                                          |

With the default 7-day window, there are about 130,000 transactions in the window. The subqueries visit about 75 million index entries in total.

### Measuring

`scripts/benchmark.py <query file>`:

1. Runs `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` once and saves the plan to `results/plans/<query>.txt`.
2. Runs the query `--runs` times (default 3), fetching every row, and records each run's time.
3. Computes an MD5 checksum of the result rows. Every later rewrite must produce the same checksum.
4. Appends the run to `results/benchmarks.csv`: median, min and max time, row count, checksum and PostgreSQL version.

Notes:
- `EXPLAIN ANALYZE` adds overhead to every plan node, so compare the measured runs, and use the plan to see where the time goes.
- The first run also reads data into cache, so it's usually the slowest.
- `--timeout-min` (default 60) cancels a run that takes too long.

```bash
uv run python scripts/benchmark.py sql/queries/01_baseline_rolling_30d.sql --runs 1
uv run python scripts/benchmark.py sql/queries/01_baseline_rolling_30d.sql --report-days 30 --runs 1
```

### Results

| Query                     | Window | Median time      | Rows | Checksum |
| ------------------------- | ------ | ---------------- | ---- | -------- |
| `01_baseline_rolling_30d` | 7 days | *to be measured* |      |          |

## Tests

```bash
make test          # unit tests, no database needed
make check         # equivalence check against a loaded database
```

- **SQL parsing:** every SQL file is parsed with PostgreSQL's own parser (via `pglast`), so syntax errors are caught without a database.
- **Generator:** run end to end on a small sample. The tests check row counts, ID ranges, value ranges, and identical output for any number of workers.
- **Plan analyzer:** a hand-written plan exercises every kind of finding.
- **Equivalence** (`scripts/check_equivalence.py`): every optimized query must return exactly the same rows (same checksum) as the query it replaces:
  - the baseline and its Step 5 rewrites
  - the same queries on each Step 4 storage layout
  - the materialized and inlined CTE versions

  A unit test fails if a new query file isn't covered by this check.

## CI/CD

`.github/workflows/ci.yml` runs on every pull request and every push to `main`:

```
lint ──┐
       ├─> integration (PostgreSQL)
test ──┘
```

| Job           | Runs                                                                                                                                              |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lint`        | `uv lock --check`, then every pre-commit hook: ruff, black, file hygiene                                                                          |
| `test`        | Unit tests (SQL parsing, generator, plan analyzer); JUnit report uploaded                                                                         |
| `integration` | Starts PostgreSQL from `docker-compose.yml`, loads a small dataset, builds every storage layout, runs the equivalence check and the plan analyzer |

CI checks **correctness** on a small dataset. **Timings** come from full-scale local runs (`make lab`), because shared CI machines give noisy timings.

The pipeline follows the same practices as a production repository:

- **Supply-chain security:**
  - actions pinned to full commit SHAs, with the version in a comment
  - a read-only token
  - no persisted git credentials
- **Reproducibility:** Python, uv and dependencies are pinned.
- **Safety and debugging:** every job has a timeout. Plans, analysis reports and PostgreSQL logs are uploaded when a job fails.
- **Same checks before commit:** pre-commit hooks run them locally (`make hooks`).
- **Automatic updates:** Dependabot opens weekly update PRs for actions and Python packages.

One-time GitHub setting: protect `main` with a ruleset (Settings → Rules → Rulesets). Use these options:

1. **Target:** include the default branch.
2. **Enforcement:** Active.
3. **Require a pull request** (0 approvals if you work alone).
4. **Require status checks:** `Lint`, `Unit tests`, `PostgreSQL integration`.
5. **Block force pushes.**

## Guides

| File                 | What it covers                                            |
| -------------------- | --------------------------------------------------------- |
| `PROJECT_STEPS.txt`  | What each step built, where it lives, how to check it     |
| `LEARNING_GUIDE.txt` | How to learn this repo, step by step                      |
| `IMPROVEMENTS.txt`   | Remaining gaps and the recommended solutions              |
| `AGENTS.md`          | Standards for anyone (or any AI agent) changing this repo |

## Project layout

```
docker-compose.yml          PostgreSQL 17 with lab settings
scripts/generate_data.py    CSV generator (random + datetime)
scripts/load_data.py        COPY into PostgreSQL, build indexes, VACUUM ANALYZE
scripts/benchmark.py        time a query, save its plan and a result checksum
scripts/analyze_plan.py     diagnose a plan: scans, loops, spills, CPU, memory
scripts/check_equivalence.py prove optimized queries return identical results
scripts/run_sql.py          run a SQL file statement by statement
scripts/run_lab.sh          run every step at full scale
scripts/db.py               connection settings
sql/schema.sql              tables
sql/indexes.sql             baseline indexes
sql/queries/                one file per query version
sql/storage/                Step 4 storage layouts (partitioned, BRIN, clustered)
results/plans/              saved EXPLAIN ANALYZE output
results/analysis/           plan analyzer reports
results/benchmarks.csv      every benchmark run
tests/                      unit tests
.github/workflows/ci.yml    CI: lint, unit tests, PostgreSQL integration
Makefile                    local commands (make help)
data/                       generated CSVs (not committed)
```
