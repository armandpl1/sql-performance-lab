"""The plan analyzer finds each kind of problem in a hand-written plan."""

from analyze_plan import build_tree, findings, report

# Unique <- Sort (spills) <- Seq Scan with date() filter, one correlated SubPlan
# executed 5,000 times, and an InitPlan.
PLAN = {
    "Plan": {
        "Node Type": "Unique", "Actual Loops": 1, "Actual Rows": 4000, "Plan Rows": 40,
        "Actual Total Time": 9000.0, "Total Cost": 123456.0,
        "Shared Hit Blocks": 1000, "Shared Read Blocks": 500, "Temp Written Blocks": 256,
        "Shared I/O Read Time": 1500.0,
        "Plans": [{
            "Node Type": "Sort", "Parent Relationship": "Outer", "Actual Loops": 1,
            "Actual Rows": 5000, "Plan Rows": 5000, "Actual Total Time": 8900.0,
            "Sort Method": "external merge", "Sort Space Type": "Disk",
            "Sort Space Used": 2048, "Temp Written Blocks": 256,
            "Plans": [{
                "Node Type": "Seq Scan", "Parent Relationship": "Outer",
                "Relation Name": "transactions", "Actual Loops": 1, "Actual Rows": 5000,
                "Plan Rows": 5000, "Actual Total Time": 8800.0,
                "Filter": "(date(transaction_timestamp) > $0)",
                "Rows Removed by Filter": 995000,
                "Plans": [
                    {"Node Type": "Aggregate", "Parent Relationship": "SubPlan",
                     "Subplan Name": "SubPlan 1", "Actual Loops": 5000, "Actual Rows": 1,
                     "Plan Rows": 1, "Actual Total Time": 1.5},
                    {"Node Type": "Aggregate", "Parent Relationship": "InitPlan",
                     "Subplan Name": "InitPlan 2", "Actual Loops": 1, "Actual Rows": 1,
                     "Plan Rows": 1, "Actual Total Time": 300.0},
                ],
            }],
        }],
    },
    "Planning Time": 1.2, "Execution Time": 9001.0,
}  # fmt: skip


def test_self_time_subtracts_children_across_loops():
    root = build_tree(PLAN["Plan"])
    scan = root.children[0].children[0]
    # 8800 total - (1.5 ms x 5000 loops) - 300 = 1000
    assert round(scan.self_ms) == 1000
    assert scan.children[0].total_ms == 7500


def test_findings_cover_each_problem():
    text = "\n".join(findings(build_tree(PLAN["Plan"])))
    assert "Sequential scan on `transactions`" in text
    assert "99.5% were thrown away" in text
    assert "Correlated subquery run 5,000 times" in text
    assert "Spill to disk" in text and "external merge" in text
    assert "Function on a column in a filter" in text
    assert "Row estimate off by 100x" in text


def test_report_summary_numbers():
    text = report(PLAN, "example", "note")
    assert "| Execution time | 9.00 s |" in text
    assert "| I/O time | 1.50 s |" in text
    assert "| CPU time (execution − I/O) | 7.50 s |" in text
    assert "| Temp files written (spill) | 2.0 MB |" in text
