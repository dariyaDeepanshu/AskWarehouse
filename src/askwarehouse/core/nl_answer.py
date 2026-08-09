"""Turns a query result into a one/two-sentence natural-language answer.
Deliberately constrained to only state numbers that are actually in the
result rows -- it's a summarization pass over ground truth, not a second
chance for the model to reason about the data."""
from askwarehouse.providers.base import Provider

SYSTEM = """Write a natural-language answer to the business question, using ONLY the numbers in \
the QUERY RESULT below. Do not compute anything not directly present in the result -- in \
particular, if the result has multiple rows (a breakdown by some dimension), do NOT sum them \
into a single total unless the question explicitly asked for a grand total; instead summarize \
the breakdown (e.g. name the top few groups and their values). If the result is a single row/\
value, answer in 1 sentence quoting that value. Do not mention SQL or tables."""


def generate_nl_answer(provider: Provider, question: str, columns: list, rows: list,
                        row_cap: int = 20) -> str:
    if not rows:
        return "The query ran successfully but returned no matching rows."
    preview = rows[:row_cap]
    result_text = f"columns: {columns}\nrows: {preview}"
    if len(rows) > row_cap:
        result_text += f"\n(... {len(rows) - row_cap} more rows not shown)"
    user = f"QUESTION: {question}\n\nQUERY RESULT ({len(rows)} row(s)):\n{result_text}"
    resp = provider.generate(SYSTEM, user, max_tokens=150, temperature=0.0)
    return resp.text.strip()
