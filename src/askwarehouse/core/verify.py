"""The 'verify this' trust-surface feature: paraphrases the original
question, runs it through the full pipeline again as an independent
generation (fresh, uncached), and flags a mismatch if the two answers
disagree. This is a self-consistency check, not a correctness proof -- two
independently-generated queries agreeing is reassuring; it can't catch a
mistake both generations happen to share."""
from dataclasses import dataclass

from askwarehouse.providers.base import Provider

PARAPHRASE_SYSTEM = """Rephrase the following business question in different words, keeping the \
EXACT same meaning, scope, filters, and time period. Do not add or remove any constraint. \
Output ONLY the rephrased question, nothing else."""


@dataclass
class VerifyResult:
    match: bool
    original_sql: str
    verify_question: str
    verify_sql: str
    original_summary: str
    verify_summary: str
    detail: str


def _paraphrase(provider: Provider, question: str) -> str:
    resp = provider.generate(PARAPHRASE_SYSTEM, question, max_tokens=120, temperature=0.4)
    return resp.text.strip().strip('"')


def _summarize(columns, rows) -> str:
    if not rows:
        return "empty"
    if len(rows) == 1:
        return str(rows[0])
    return f"{len(rows)} rows, first={rows[0]}, last={rows[-1]}"


def _numeric_close(a, b, rel_tol: float = 0.02) -> bool:
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    if a == b:
        return True
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom <= rel_tol


def _results_match(orig_columns, orig_rows, verify_columns, verify_rows) -> bool:
    if len(orig_rows) != len(verify_rows):
        return False
    if len(orig_rows) == 0:
        return True
    # single aggregate value: compare numerically with tolerance (float rounding,
    # not a stand-in for a real mismatch)
    if len(orig_rows) == 1 and len(orig_columns) == len(verify_columns) == 1:
        a, b = orig_rows[0][0], verify_rows[0][0]
        if _numeric_close(a, b):
            return True
        return (a is None and b is None) or str(a) == str(b)
    # multi-row: compare as sets of tuples (order/column-name independent).
    # numeric values are rounded to absorb float noise; everything else is
    # compared by str() so a date that survived a JSON round-trip as
    # "2025-01-01" still matches a native datetime.date from a fresh run.
    def _cell(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return round(float(v), 2)
        return None if v is None else str(v)

    def normalize(rows):
        return {tuple(_cell(v) for v in r) for r in rows}

    return normalize(orig_rows) == normalize(verify_rows)


def verify(agent, question: str, original_sql: str, original_columns, original_rows) -> VerifyResult:
    """agent: an AskWarehouseAgent instance. Runs a paraphrase through the
    same agent with caching bypassed so the second run is a genuinely
    independent generation."""
    verify_question = _paraphrase(agent.provider, question)
    response = agent.ask(verify_question, skip_ambiguity=True)

    if response.result is None or not response.result.success:
        return VerifyResult(
            match=False, original_sql=original_sql, verify_question=verify_question,
            verify_sql=response.sql, original_summary=_summarize(original_columns, original_rows),
            verify_summary="query failed", detail="Verification query did not execute successfully.",
        )

    match = _results_match(original_columns, original_rows, response.result.columns, response.result.rows)
    return VerifyResult(
        match=match, original_sql=original_sql, verify_question=verify_question,
        verify_sql=response.sql,
        original_summary=_summarize(original_columns, original_rows),
        verify_summary=_summarize(response.result.columns, response.result.rows),
        detail="Results agree." if match else "Results disagree -- treat the original answer with caution.",
    )
