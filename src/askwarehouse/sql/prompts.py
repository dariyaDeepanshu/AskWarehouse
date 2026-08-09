DIALECT_NOTES = {
    "duckdb": (
        "Dialect: DuckDB. Use current_date, date_diff('day', a, b), date_trunc, "
        "strftime for formatting, INTERVAL n DAY, QUALIFY for window filters."
    ),
    "sqlite": (
        "Dialect: SQLite. Use date('now'), julianday(a) - julianday(b) for day diffs, "
        "strftime('%Y-%m', col) for month truncation. No QUALIFY -- use a subquery."
    ),
}

GENERATE_SYSTEM = """You are an expert {dialect} SQL analyst. Write ONE read-only SQL query \
(SELECT or WITH ... SELECT only) that answers the business question, using ONLY the tables and \
columns given in the schema below. {dialect_note}

Rules:
- Use only columns that appear in the schema block. Never invent a table or column.
- If VALUE HINTS are given, use the exact stored value shown, not the literal wording in the question.
- Follow the plan's stated grain: if it says one row per customer, aggregate down to that \
  grain -- do not leave the result at a finer grain than asked.
- If a one-to-many join is needed alongside an aggregate measure that is already pre-aggregated \
  at a coarser grain in another table (e.g. an order-level total), aggregate at the coarser \
  grain first (or use SUM(DISTINCT ...)-safe pre-aggregation) rather than summing the coarse \
  measure once per joined row.
- Include an explicit LIMIT unless the question clearly wants every row of a small, already-\
  aggregated result.
- Output ONLY the SQL query. No markdown fences, no explanation, no trailing commentary."""

CRITIQUE_SYSTEM = """You are reviewing a SQL query before it runs against a read-only warehouse. \
Check it against the plan and schema for exactly these failure modes: \
(1) wrong grain -- result is finer or coarser than the plan's stated grain, \
(2) double-counting from a one-to-many join, \
(3) a filter value that doesn't match the VALUE HINTS given, \
(4) a column or table not present in the schema, \
(5) missing a status/date filter clearly implied by the question. \
If the query has any of these problems, output a corrected query. If it's already correct, \
output it unchanged. Output ONLY the final SQL query, no explanation, no markdown fences."""


def build_generate_user_prompt(question: str, schema_context: str, value_hints: str,
                                plan_text: str) -> str:
    parts = [f"SCHEMA:\n{schema_context}"]
    if value_hints:
        parts.append(value_hints)
    if plan_text:
        parts.append(f"PLAN:\n{plan_text}")
    parts.append(f"QUESTION: {question}")
    return "\n\n".join(parts)


def build_critique_user_prompt(question: str, schema_context: str, value_hints: str,
                                plan_text: str, sql: str) -> str:
    parts = [f"SCHEMA:\n{schema_context}"]
    if value_hints:
        parts.append(value_hints)
    if plan_text:
        parts.append(f"PLAN:\n{plan_text}")
    parts.append(f"QUESTION: {question}")
    parts.append(f"CANDIDATE SQL:\n{sql}")
    return "\n\n".join(parts)


def build_repair_user_prompt(question: str, schema_context: str, failed_sql: str,
                              error_message: str) -> str:
    return (
        f"SCHEMA:\n{schema_context}\n\n"
        f"QUESTION: {question}\n\n"
        f"This query failed:\n{failed_sql}\n\n"
        f"Database error:\n{error_message}\n\n"
        f"Fix the query so it runs successfully and still answers the question. "
        f"Output ONLY the corrected SQL query."
    )
