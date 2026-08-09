"""Post-execution sanity checks. These run on queries that already executed
successfully -- the repair loop only catches queries that error out, but the
classic silent-wrong-answer case (double-counting after a 1:many join) runs
fine and returns a number, just the wrong one. These are heuristics, not
proofs -- they flag findings for the trust surface (task 13), they don't
block the answer."""
import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from askwarehouse.execution.sandbox import ExecutionResult

# columns that are pre-aggregated at the fact_orders (order) grain -- summing
# these again after a join down to a finer-grained table (fact_order_items,
# fact_payments, fact_campaign_touches) multiplies them per joined row.
COARSE_GRAIN_MEASURES = {"order_total", "amount_collected", "item_count", "unit_count"}
FINE_GRAIN_TABLES = {"fact_order_items", "fact_payments", "fact_campaign_touches"}


@dataclass
class SanityFinding:
    code: str
    severity: str  # 'info' | 'warning'
    message: str


def _possible_fanout_double_count(sql_text: str, dialect: str) -> SanityFinding | None:
    try:
        tree = sqlglot.parse_one(sql_text, read=dialect)
    except Exception:
        return None

    tables = {t.name.lower() for t in tree.find_all(exp.Table)}
    joined_fine_tables = tables & FINE_GRAIN_TABLES
    if not joined_fine_tables:
        return None
    if "fact_orders" not in tables and not joined_fine_tables:
        return None

    agg_funcs = [f for f in tree.find_all((exp.Sum, exp.Avg))]
    for f in agg_funcs:
        for col in f.find_all(exp.Column):
            if col.name.lower() in COARSE_GRAIN_MEASURES:
                return SanityFinding(
                    code="possible_fanout_double_count",
                    severity="warning",
                    message=(
                        f"Query SUMs/AVGs '{col.name}' (pre-aggregated at the order grain) "
                        f"while also joining {sorted(joined_fine_tables)} (a finer grain). "
                        f"If the join is one-to-many, this value is likely inflated -- "
                        f"aggregate at the order grain first, or aggregate the fine-grain "
                        f"table separately."
                    ),
                )
    return None


def _truncated_by_limit(sql_text: str, result: ExecutionResult, dialect: str) -> SanityFinding | None:
    try:
        tree = sqlglot.parse_one(sql_text, read=dialect)
    except Exception:
        return None
    limit_node = tree.args.get("limit")
    if limit_node is None:
        return None
    try:
        limit_n = int(str(limit_node.expression.this))
    except (ValueError, AttributeError):
        return None
    if result.row_count == limit_n and limit_n > 0:
        return SanityFinding(
            code="result_truncated_by_limit",
            severity="info",
            message=f"Result has exactly {limit_n} rows, matching the query's LIMIT -- there may be more rows not shown.",
        )
    return None


def _null_heavy_columns(result: ExecutionResult, null_fraction_threshold: float = 0.5) -> list[SanityFinding]:
    findings = []
    if not result.rows or not result.columns:
        return findings
    n = len(result.rows)
    for i, col in enumerate(result.columns):
        nulls = sum(1 for row in result.rows if row[i] is None)
        frac = nulls / n
        if frac >= null_fraction_threshold and n >= 5:
            findings.append(SanityFinding(
                code="null_heavy_column",
                severity="warning",
                message=f"Column '{col}' is NULL in {frac:.0%} of rows -- check for an unintended LEFT JOIN or missing filter.",
            ))
    return findings


def run_sanity_checks(sql_text: str, result: ExecutionResult, dialect: str = "duckdb") -> list[SanityFinding]:
    findings: list[SanityFinding] = []

    if result.success and result.row_count == 0:
        findings.append(SanityFinding(
            code="empty_result", severity="warning",
            message="Query executed successfully but returned zero rows -- check filter values against VALUE HINTS.",
        ))

    if result.success and result.row_count > 0:
        fanout = _possible_fanout_double_count(sql_text, dialect)
        if fanout:
            findings.append(fanout)
        trunc = _truncated_by_limit(sql_text, result, dialect)
        if trunc:
            findings.append(trunc)
        findings.extend(_null_heavy_columns(result))

    return findings
