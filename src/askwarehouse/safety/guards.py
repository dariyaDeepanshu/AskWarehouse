"""Static safety guards: everything here runs on the SQL text/AST *before*
a database connection is ever opened for that query. A rejection here never
touches the database at all -- it's a pure sqlglot-level check, independent
of the read-only connection guarantee in execution/connection.py.

Order matters: parse -> statement count -> statement type -> table allowlist
-> PII column check -> LIMIT injection -> (caller runs EXPLAIN separately,
since that needs a live connection)."""
import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from askwarehouse.safety.config import SafetyConfig, DEFAULT_SAFETY_CONFIG

_DIALECT_MAP = {"duckdb": "duckdb", "sqlite": "sqlite"}


@dataclass
class GuardResult:
    allowed: bool
    sql: str
    reason: str | None = None
    estimated_rows: int | None = None
    # 'policy' = a real safety/cost rejection; 'invalid_sql' = the query doesn't
    # even bind (bad column/table/syntax) -- that's a correctness error, not a
    # safety rejection, and should be routed back through the repair loop like
    # any other DB error rather than counted as a guard rejection.
    kind: str = "policy"


def _cte_names(tree: exp.Expression) -> set[str]:
    return {cte.alias.lower() for cte in tree.find_all(exp.CTE) if cte.alias}


def static_check(sql_text: str, known_tables: set[str], dialect: str = "duckdb",
                  config: SafetyConfig = DEFAULT_SAFETY_CONFIG) -> GuardResult:
    d = _DIALECT_MAP[dialect]

    try:
        statements = [s for s in sqlglot.parse(sql_text, read=d) if s is not None]
    except Exception as e:
        return GuardResult(allowed=False, sql=sql_text, reason=f"sql did not parse: {e}")

    if len(statements) != config.max_statements_per_query:
        return GuardResult(allowed=False, sql=sql_text,
                            reason=f"expected exactly {config.max_statements_per_query} statement, got {len(statements)}")

    tree = statements[0]

    if not isinstance(tree, exp.Select):
        return GuardResult(allowed=False, sql=sql_text,
                            reason=f"only SELECT/WITH is allowed, got {type(tree).__name__}")

    # defensively scan for anything DDL/DML/command-like anywhere in the tree
    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter,
                 exp.Command, exp.Copy, exp.Attach if hasattr(exp, "Attach") else exp.Command)
    for node in tree.walk():
        if isinstance(node, forbidden):
            return GuardResult(allowed=False, sql=sql_text,
                                reason=f"forbidden statement type in query: {type(node).__name__}")

    # table allowlist -- exclude CTE-defined names, those aren't real tables
    cte_names = _cte_names(tree)
    referenced = {t.name.lower() for t in tree.find_all(exp.Table)} - cte_names
    unknown = referenced - known_tables
    if unknown:
        return GuardResult(allowed=False, sql=sql_text,
                            reason=f"query references table(s) not in the retrieved/allowed schema: {sorted(unknown)}")

    # PII column check, by column name regardless of qualifier -- these names
    # are distinctive enough that this is safe and doesn't need table resolution
    pii_columns = {col.lower() for _table, col in config.pii_denylist}
    used_columns = {c.name.lower() for c in tree.find_all(exp.Column)}
    hit = used_columns & pii_columns
    if hit:
        return GuardResult(allowed=False, sql=sql_text,
                            reason=f"query touches denylisted PII column(s): {sorted(hit)}")

    # LIMIT injection / clamping on the outermost query
    existing_limit = tree.args.get("limit")
    if existing_limit is None:
        tree.set("limit", exp.Limit(expression=exp.Literal.number(config.max_rows)))
    else:
        try:
            n = int(str(existing_limit.expression.this))
            if n > config.max_rows:
                tree.set("limit", exp.Limit(expression=exp.Literal.number(config.max_rows)))
        except (ValueError, AttributeError):
            tree.set("limit", exp.Limit(expression=exp.Literal.number(config.max_rows)))

    return GuardResult(allowed=True, sql=tree.sql(dialect=d))


_ROW_ESTIMATE_RE = re.compile(r"~\s*([\d,]+)\s*rows", re.IGNORECASE)


def explain_cost_check(con, sql_text: str, config: SafetyConfig = DEFAULT_SAFETY_CONFIG) -> GuardResult:
    """Runs EXPLAIN (not EXPLAIN ANALYZE -- never executes the query) and
    rejects if DuckDB's own optimizer estimates a larger intermediate/final
    row count than the configured ceiling. Requires a live connection, so
    it's a separate call from static_check (which needs none)."""
    try:
        rows = con.execute(f"EXPLAIN {sql_text}").fetchall()
    except Exception as e:
        # EXPLAIN still binds the query (resolves tables/columns/types), so a
        # failure here is usually a genuine SQL error (bad column, type
        # mismatch, ...), not a cost/policy issue -- surface the real DB
        # error text so the repair loop can act on it like any other failure.
        return GuardResult(allowed=False, sql=sql_text, reason=str(e), kind="invalid_sql")

    plan_text = "\n".join(str(r) for r in rows)
    estimates = [int(m.replace(",", "")) for m in _ROW_ESTIMATE_RE.findall(plan_text)]
    max_estimate = max(estimates) if estimates else None

    if max_estimate is not None and max_estimate > config.max_explain_row_estimate:
        return GuardResult(allowed=False, sql=sql_text, estimated_rows=max_estimate,
                            reason=f"EXPLAIN estimates {max_estimate:,} rows, exceeds cap of {config.max_explain_row_estimate:,}")

    return GuardResult(allowed=True, sql=sql_text, estimated_rows=max_estimate)
