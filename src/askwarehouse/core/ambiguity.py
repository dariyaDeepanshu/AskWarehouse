"""Ambiguity check: the second stage of the pipeline, right after schema
retrieval and before any SQL gets written. Deliberately biased against
over-asking -- the semantic layer already resolves the classic "top
customers by what?" case (see metric_customer_revenue), so this should only
fire when there's a genuine fork in what the SQL would compute, not just
because the question uses an informal phrase."""
from dataclasses import dataclass

from askwarehouse.providers.base import Provider
from askwarehouse.core.json_util import extract_json

SYSTEM_PROMPT = """You are the ambiguity gate in a text-to-SQL analytics agent. \
You decide whether a business question can be turned into ONE clearly-correct SQL query \
against the given schema, or whether it is genuinely ambiguous and a clarifying question \
is needed first.

Bias strongly toward NOT asking. Only flag ambiguous=true when there are at least two \
substantively different SQL queries a reasonable analyst could write, AND the schema/semantic \
layer does not already pick a default for it. Do NOT flag ambiguous just because the question \
uses an informal phrase ("top", "recent", "good") if the schema exposes a single canonical \
metric or a sensible default (e.g. "all time" when no period is given) resolves it.

Examples:
Q: "Who are the top customers?" / schema has metric_customer_revenue (a single canonical \
revenue metric) -> ambiguous=false (revenue is the obvious default; use metric_customer_revenue).
Q: "What are our best products?" / schema has metric_product_performance with revenue, \
units_sold, AND gross_profit as three genuinely different rankings, none marked as default \
-> ambiguous=true, ask which metric.
Q: "How did sales trend recently?" with no schema-level default time window -> ambiguous=true, \
ask for the period.
Q: "How many orders were completed last month?" -> ambiguous=false (fully specified).

Respond with ONLY a JSON object: {"ambiguous": bool, "reason": "<short reason>", \
"clarifying_question": "<question to ask the user, or null if not ambiguous>"}"""


@dataclass
class AmbiguityResult:
    is_ambiguous: bool
    reason: str
    clarifying_question: str | None
    raw: str = ""


class AmbiguityChecker:
    def __init__(self, provider: Provider):
        self.provider = provider

    def check(self, question: str, schema_context: str) -> AmbiguityResult:
        user = f"SCHEMA (retrieved subset):\n{schema_context}\n\nQUESTION: {question}"
        resp = self.provider.generate(SYSTEM_PROMPT, user, max_tokens=300, temperature=0.0)
        try:
            data = extract_json(resp.text)
            return AmbiguityResult(
                is_ambiguous=bool(data.get("ambiguous", False)),
                reason=data.get("reason", ""),
                clarifying_question=data.get("clarifying_question") or None,
                raw=resp.text,
            )
        except Exception:
            # fail safe: if we can't parse the gate's answer, don't block the user
            return AmbiguityResult(is_ambiguous=False, reason="parse_failure", clarifying_question=None, raw=resp.text)
