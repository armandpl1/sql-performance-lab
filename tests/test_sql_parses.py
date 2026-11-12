"""Every SQL file must be valid PostgreSQL syntax.

Uses pglast, which wraps PostgreSQL's own parser, so this catches syntax
errors without a running database.
"""

from pathlib import Path

import pglast
import pytest
from benchmark import render

ROOT = Path(__file__).resolve().parent.parent

SQL_FILES = sorted((ROOT / "sql").rglob("*.sql"))


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_sql_file_parses(path):
    pglast.parse_sql(render(path.read_text(), report_days=7))


def test_report_days_is_substituted():
    sql = (ROOT / "sql/queries/01_baseline_rolling_30d.sql").read_text()
    rendered = render(sql, report_days=7)
    assert ":report_days" not in rendered
    assert "- 7" in rendered
