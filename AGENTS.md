# AGENTS.md

Standards for anyone changing this repository, human or AI agent. Follow them
on every change.

## Workflow

1. **Branch off the latest `main`.** `main` is protected: changes go through a
   pull request, and the checks `Lint`, `Unit tests` and
   `PostgreSQL integration` must pass.
2. **Plan, build, verify, document, then commit**, in that order.
3. **Verify with real runs, not assumptions.** Run the code, the tests and the
   queries. Never report a result that wasn't measured. Write "to be
   measured" instead.
4. **Before committing:** `make ci` (lint and unit tests). If SQL changed, also
   run `make integration` (needs Docker), or rely on the CI integration job.
5. **Commit messages:** a short summary line, a blank line, then bullet points
   saying what changed and why.
6. **No AI attribution.** No `Co-Authored-By` or "Generated with" lines in
   commits or pull requests. Commits appear as the repository owner only.
7. **Never rewrite published history** (force push) without the owner's explicit
   go-ahead.

## SQL and performance standards

- **Change one thing at a time,** and measure before and after with
  `scripts/benchmark.py`.
- **Every optimized query must return exactly the same rows** as the query it
  replaces. Add every new query file to `scripts/check_equivalence.py`, either
  in an equivalence group or in RUN_ONLY. A unit test fails otherwise.
- **Back performance claims** with a saved plan (`results/plans/`) and an
  analyzer report (`results/analysis/`).
- **Timings come from full-scale local runs.** CI checks correctness only.
- **Write SQL the engine can optimize:**
  - compare bare indexed columns with constants (no functions around them)
  - avoid correlated subqueries in SELECT
  - read each table once where possible
- **Comment every query file:** the step, what it computes, and why it is
  written that way.

## Python standards

- **Environment:** Python 3.11, dependencies managed with uv and pinned in
  `uv.lock`. Add packages with `uv add`, never pip.
- **Linting:** ruff and black, run by pre-commit hooks (`make hooks`).
- **Determinism:** the generator must produce identical output for the same
  seed, with any number of workers. A refactor that changes the generated data
  is a bug unless intended and stated.
- **Tests** live in `tests/`, one module per script or feature. New logic needs
  a test.

## Documentation standards

- **README.md** is the source of truth for design, commands and results.
- **Keep the guides current** when a step changes:
  - `PROJECT_STEPS.txt`: what was built and how to check it
  - `LEARNING_GUIDE.txt`: how to learn the repo
  - `IMPROVEMENTS.txt`: gaps and recommended solutions
- **Plain language:** short sentences, no jargon without explanation.
- **Markdown tables** have their `|` characters aligned in the raw file.

## CI standards

- **Pin actions to full commit SHAs,** with the version in a comment.
- **Least privilege:** read-only token by default, write permissions only on
  the job that needs them.
- **Every job has a timeout** and uploads what's needed to debug a failure.
- **Don't rename CI job names** without also updating the branch ruleset's
  required checks.
- **Validate workflow changes** with actionlint:
  `uvx --from actionlint-py actionlint .github/workflows/ci.yml`

## Harnesses

| Tool                           | Use it to                                                |
| ------------------------------ | -------------------------------------------------------- |
| `make help`                    | List every command                                       |
| `scripts/benchmark.py`         | Time a query, save its plan, checksum its rows           |
| `scripts/analyze_plan.py`      | Find scans, repeated loops, spills, CPU and memory costs |
| `scripts/check_equivalence.py` | Prove optimized queries return identical rows            |
| `scripts/run_sql.py`           | Run a SQL file statement by statement (DDL, VACUUM)      |
| `scripts/run_lab.sh`           | Run every step at full scale                             |
| `make integration`             | Run the CI integration job locally                       |
