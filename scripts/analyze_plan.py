#!/usr/bin/env python3
"""Diagnose a query's bottlenecks from its EXPLAIN ANALYZE plan.

Runs EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) on a query file, saves
the JSON plan, and writes a Markdown report that lists:

    Summary          planning and execution time, estimated total cost,
                     I/O time vs. CPU time, buffers, memory, temp files
    Time by node     where the time goes, by each node's own (self) time
    Findings         sequential scans, nodes run many times (nested loops
                     and correlated subqueries), spills to disk, functions
                     wrapped around columns in filters, bad row estimates

Usage:
    python scripts/analyze_plan.py sql/queries/01_baseline_rolling_30d.sql
    python scripts/analyze_plan.py sql/queries/01_baseline_rolling_30d.sql --set work_mem=4MB
    python scripts/analyze_plan.py --from-json results/plans/01_baseline_rolling_30d.json

How some numbers are derived (PostgreSQL doesn't report them directly):
    Self time   a node's total time (time per loop x loops) minus its
                children's total time. Approximate for parallel nodes,
                whose times are averaged across workers.
    CPU time    execution time minus I/O time (needs track_io_timing=on).
                For parallel plans this is the leader's wall time, not the
                sum of all workers' CPU.
    Memory      the largest working memory reported by any sort, hash or
                aggregate node, plus the planner's own memory (PostgreSQL 17+).
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANS_DIR = ROOT / "results/plans"
REPORTS_DIR = ROOT / "results/analysis"
BLOCK_KB = 8  # PostgreSQL page size

# Thresholds for findings
MANY_LOOPS = 1_000
SEQ_SCAN_MIN_ROWS = 100_000
MISESTIMATE_FACTOR = 10
FUNCTION_IN_FILTER = re.compile(
    r"\b(date|lower|upper|date_trunc|extract|coalesce)\s*\(", re.IGNORECASE
)


@dataclass
class Node:
    """One plan node with the numbers the report needs."""

    path: str  # e.g. "1.2.1", position in the tree
    depth: int
    node_type: str
    relation: str | None
    index: str | None
    relationship: str | None  # Outer / Inner / SubPlan / InitPlan / Member
    subplan_name: str | None
    loops: int
    rows_per_loop: float
    plan_rows: float
    total_ms: float  # across all loops
    self_ms: float = 0.0
    raw: dict = field(repr=False, default_factory=dict)
    children: list = field(repr=False, default_factory=list)

    @property
    def label(self) -> str:
        text = self.node_type
        if self.index:
            text += f" using {self.index}"
        if self.relation:
            text += f" on {self.relation}"
        if self.subplan_name:
            text = f"{self.subplan_name}: {text}"
        return text


def build_tree(plan: dict, path="1", depth=0) -> Node:
    loops = plan.get("Actual Loops", 1) or 1
    node = Node(
        path=path,
        depth=depth,
        node_type=plan["Node Type"]
        + (
            f" ({plan['Strategy']})"
            if plan.get("Strategy") not in (None, "Plain")
            else ""
        ),
        relation=plan.get("Relation Name"),
        index=plan.get("Index Name"),
        relationship=plan.get("Parent Relationship"),
        subplan_name=plan.get("Subplan Name"),
        loops=loops,
        rows_per_loop=plan.get("Actual Rows", 0),
        plan_rows=plan.get("Plan Rows", 0),
        total_ms=plan.get("Actual Total Time", 0.0) * loops,
        raw=plan,
    )
    node.children = [
        build_tree(child, f"{path}.{i}", depth + 1)
        for i, child in enumerate(plan.get("Plans", []), start=1)
    ]
    node.self_ms = max(node.total_ms - sum(c.total_ms for c in node.children), 0.0)
    return node


def walk(node: Node):
    yield node
    for child in node.children:
        yield from walk(child)


def io_ms(plan: dict) -> float:
    """I/O time at a node. Key names changed in PostgreSQL 17, so match both."""
    return sum(v for k, v in plan.items() if "I/O" in k and "Time" in k)


def fmt_ms(ms: float) -> str:
    return f"{ms / 1000:,.2f} s" if ms >= 1000 else f"{ms:,.1f} ms"


def fmt_kb(kb: float) -> str:
    return f"{kb / 1024:,.1f} MB" if kb >= 1024 else f"{kb:,.0f} kB"


def node_memory_kb(raw: dict) -> float:
    """Working memory a sort, hash or aggregate node reports (kB)."""
    if raw.get("Sort Space Type") == "Memory":
        return raw.get("Sort Space Used", 0)
    return raw.get("Peak Memory Usage", 0)


def node_spill_kb(raw: dict) -> float:
    """Disk a node spilled to (kB): sort on disk, hash/aggregate batches, temp blocks."""
    kb = 0.0
    if raw.get("Sort Space Type") == "Disk":
        kb = max(kb, raw.get("Sort Space Used", 0))
    kb = max(kb, raw.get("Disk Usage", 0))  # HashAggregate
    return max(kb, raw.get("Temp Written Blocks", 0) * BLOCK_KB)


def findings(root: Node) -> list[str]:
    out = []
    nodes = list(walk(root))

    for n in nodes:
        raw = n.raw
        removed = raw.get("Rows Removed by Filter", 0) * n.loops
        returned = n.rows_per_loop * n.loops

        # Sequential scans over big tables
        if raw["Node Type"] == "Seq Scan" and returned + removed >= SEQ_SCAN_MIN_ROWS:
            share = removed / (returned + removed) if returned + removed else 0
            out.append(
                f"**Sequential scan on `{n.relation}`** (node {n.path}): read "
                f"{returned + removed:,.0f} rows to return {returned:,.0f}; "
                f"{share:.1%} were thrown away by the filter `{raw.get('Filter', '')}`. "
                f"Took {fmt_ms(n.total_ms)}."
            )

        # Anything executed many times: correlated subqueries, nested-loop inner sides
        if n.loops >= MANY_LOOPS and n.relationship in ("SubPlan", "Inner"):
            kind = (
                "Correlated subquery"
                if n.relationship == "SubPlan"
                else "Nested loop inner side"
            )
            out.append(
                f"**{kind} run {n.loops:,} times**: `{n.label}` (node {n.path}). "
                f"{fmt_ms(n.total_ms / n.loops)} per run, {fmt_ms(n.total_ms)} in total, "
                f"{removed:,.0f} rows read and discarded by its filter across all runs."
            )

        if raw["Node Type"] == "Nested Loop" and n.children:
            outer_rows = n.children[0].rows_per_loop * n.children[0].loops
            if outer_rows >= MANY_LOOPS:
                out.append(
                    f"**Nested loop join** (node {n.path}): the inner side runs once per "
                    f"outer row, {outer_rows:,.0f} times. Took {fmt_ms(n.total_ms)}."
                )

        # Spills to disk
        spill = node_spill_kb(raw)
        if spill:
            detail = raw.get("Sort Method") or (
                f"{raw.get('Hash Batches') or raw.get('HashAgg Batches')} batches"
            )
            out.append(
                f"**Spill to disk** in `{n.label}` (node {n.path}): wrote {fmt_kb(spill)} of "
                f"temporary data ({detail}). It needed more than work_mem."
            )

        # Functions wrapped around columns in filters or conditions
        for key in ("Filter", "Index Cond", "Join Filter", "Hash Cond"):
            condition = raw.get(key, "")
            if FUNCTION_IN_FILTER.search(condition):
                out.append(
                    f"**Function on a column in a {key.lower()}** (node {n.path}, "
                    f"`{n.label}`): `{condition}`. An index on the bare column can't be "
                    f"used for this condition."
                )
                break

        # Planner row estimates far from reality
        if n.plan_rows and n.rows_per_loop and n.relationship != "InitPlan":
            ratio = n.rows_per_loop / n.plan_rows
            if ratio >= MISESTIMATE_FACTOR or ratio <= 1 / MISESTIMATE_FACTOR:
                out.append(
                    f"**Row estimate off by {max(ratio, 1 / ratio):,.0f}x** at `{n.label}` "
                    f"(node {n.path}): planned {n.plan_rows:,.0f} rows, got "
                    f"{n.rows_per_loop:,.0f} per loop. Bad estimates lead to bad plan choices."
                )

    if not any("Spill to disk" in f for f in out):
        out.append(
            "**No spill to disk.** Every sort, hash and aggregate fit in work_mem."
        )
    return out


def report(doc: dict, name: str, settings_note: str) -> str:
    root = build_tree(doc["Plan"])
    nodes = list(walk(root))
    execution_ms = doc.get("Execution Time", 0.0)
    planning_ms = doc.get("Planning Time", 0.0)
    top = doc["Plan"]
    io_time = io_ms(top)
    hit = top.get("Shared Hit Blocks", 0)
    read = top.get("Shared Read Blocks", 0)
    temp_written = top.get("Temp Written Blocks", 0)
    max_mem_kb = max((node_memory_kb(n.raw) for n in nodes), default=0)
    planning = doc.get("Planning", {})
    planner_mem = planning.get("Memory Used")
    jit = doc.get("JIT", {})
    settings = doc.get("Settings", {})

    lines = [
        f"# Plan analysis: `{name}`",
        "",
        settings_note,
        "",
        "## Summary",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Execution time | {fmt_ms(execution_ms)} |",
        f"| Planning time | {fmt_ms(planning_ms)} |",
        f"| Estimated total cost | {top.get('Total Cost', 0):,.0f} (planner units) |",
        f"| Rows returned | {top.get('Actual Rows', 0):,} |",
        f"| I/O time | {fmt_ms(io_time)} |",
        f"| CPU time (execution − I/O) | {fmt_ms(max(execution_ms - io_time, 0))} |",
        (
            f"| Buffers | {hit:,} hit in cache, {read:,} read from disk "
            f"({fmt_kb((hit + read) * BLOCK_KB)} touched) |"
        ),
        f"| Largest working memory (sort/hash/agg) | {fmt_kb(max_mem_kb)} |",
        f"| Temp files written (spill) | {fmt_kb(temp_written * BLOCK_KB)} |",
    ]
    if planner_mem is not None:
        lines.append(f"| Planner memory | {fmt_kb(planner_mem)} |")
    if jit:
        jit_ms = jit.get("Timing", {}).get("Total", 0)
        lines.append(
            f"| JIT compilation | {jit.get('Functions', 0)} functions, {fmt_ms(jit_ms)} |"
        )
    if settings:
        lines.append(
            "| Non-default settings | "
            + ", ".join(f"{k}={v}" for k, v in sorted(settings.items()))
            + " |"
        )

    lines += [
        "",
        "## Time by node",
        "",
        (
            "Self time = the node's own work, excluding its children. "
            "Loops = how many times the node ran."
        ),
        "",
        "| Node | Operation | Loops | Rows/loop | Self time | Share |",
        "|---|---|---|---|---|---|",
    ]
    total_self = sum(n.self_ms for n in nodes) or 1
    for n in sorted(nodes, key=lambda n: n.self_ms, reverse=True)[:12]:
        lines.append(
            f"| {n.path} | {'· ' * n.depth}{n.label} | {n.loops:,} | {n.rows_per_loop:,.0f} | "
            f"{fmt_ms(n.self_ms)} | {n.self_ms / total_self:.0%} |"
        )

    lines += ["", "## Findings", ""]
    lines += [f"- {f}" for f in findings(root)]

    lines += ["", "## Plan tree", "", "```"]
    for n in nodes:
        lines.append(
            f"{'  ' * n.depth}{n.path} {n.label}  "
            f"(loops={n.loops:,} rows={n.rows_per_loop:,.0f} total={fmt_ms(n.total_ms)})"
        )
    lines += ["```", ""]
    return "\n".join(lines)


def explain(
    query_file: Path, report_days: int, set_options: list[str], timeout_min: float
):
    from benchmark import render  # needs psycopg only when running against the database
    from db import connect

    sql = render(query_file.read_text(), report_days)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = '{int(timeout_min * 60_000)}ms'")
        for option in set_options:
            key, value = option.split("=", 1)
            cur.execute(f"SET {key} = %s", (value,))
        cur.execute("SHOW server_version_num")
        memory = ", MEMORY" if int(cur.fetchone()[0]) >= 170000 else ""
        cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, SETTINGS{memory}, FORMAT JSON) " + sql)
        result = cur.fetchone()[0]
    return result[0] if isinstance(result, list) else json.loads(result)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("query_file", type=Path, nargs="?")
    parser.add_argument(
        "--from-json", type=Path, help="analyze a saved JSON plan instead"
    )
    parser.add_argument("--report-days", type=int, default=7)
    parser.add_argument(
        "--set", action="append", default=[], metavar="NAME=VALUE",
        help="session setting for this run, e.g. work_mem=4MB (repeatable)",
    )  # fmt: skip
    parser.add_argument("--timeout-min", type=float, default=60)
    parser.add_argument("--suffix", default="", help="added to output file names")
    args = parser.parse_args()

    if args.from_json:
        doc = json.loads(args.from_json.read_text())
        name = args.from_json.stem
        note = f"Analyzed from saved plan `{args.from_json.name}`."
    else:
        if not args.query_file:
            parser.error("give a query file or --from-json")
        name = args.query_file.stem + args.suffix
        doc = explain(args.query_file, args.report_days, args.set, args.timeout_min)
        PLANS_DIR.mkdir(parents=True, exist_ok=True)
        (PLANS_DIR / f"{name}.json").write_text(json.dumps(doc, indent=2))
        extra = f", with {', '.join(args.set)}" if args.set else ""
        note = f"`report_days={args.report_days}`{extra}. JSON plan: `results/plans/{name}.json`."

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"{name}.md"
    out.write_text(report(doc, name, note))
    print(f"Report written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
