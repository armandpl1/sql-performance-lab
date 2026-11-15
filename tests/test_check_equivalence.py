"""The equivalence check covers every query file, and only real ones."""

from pathlib import Path

from check_equivalence import EQUIVALENT_GROUPS, RUN_ONLY

QUERIES = Path(__file__).resolve().parent.parent / "sql/queries"


def test_every_listed_query_exists():
    listed = [n for names in EQUIVALENT_GROUPS.values() for n in names] + RUN_ONLY
    missing = [n for n in listed if not (QUERIES / f"{n}.sql").exists()]
    assert not missing


def test_every_query_file_is_checked_in_ci():
    listed = {n for names in EQUIVALENT_GROUPS.values() for n in names} | set(RUN_ONLY)
    unchecked = {p.stem for p in QUERIES.glob("*.sql")} - listed
    assert not unchecked, f"add these to check_equivalence.py: {sorted(unchecked)}"


def test_groups_compare_at_least_two_queries():
    assert all(len(names) >= 2 for names in EQUIVALENT_GROUPS.values())
