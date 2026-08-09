import re


def clean_sql(text: str) -> str:
    """Strips markdown fences / stray prose the model sometimes wraps SQL
    in, and drops a trailing semicolon (guards/execution add their own)."""
    text = text.strip()
    fence = re.search(r"```(?:sql)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    # if the model added a sentence before/after the statement, keep from
    # the first SELECT/WITH to the end
    match = re.search(r"\b(SELECT|WITH)\b", text, re.IGNORECASE)
    if match:
        text = text[match.start():]
    return text.strip().rstrip(";").strip()
