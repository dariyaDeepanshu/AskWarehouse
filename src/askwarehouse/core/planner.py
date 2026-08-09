"""Plan step: forces the model to name the join path and output grain in
plain text *before* writing SQL. This is the direct countermeasure to the
classic silent-wrong-answer failure -- fan-out double counting after a 1:many
join -- because the grain is stated as an explicit claim that the sanity
checker (core/sanity.py) can later cross-check against the actual result
cardinality."""
from dataclasses import dataclass

from askwarehouse.providers.base import Provider

SYSTEM_PROMPT = """You are the planning step of a text-to-SQL agent. Given a business \
question and a retrieved schema subset, do NOT write SQL yet. Instead state, in a few short \
lines:
1. GRAIN: what one row of the final result represents (e.g. "one row per customer", \
"one row per order", "one row per (month, region)").
2. TABLES: which retrieved table(s) are needed.
3. JOINS: the join path between them, and whether any join is one-to-many (which risks \
double-counting a measure if you're not careful about where you aggregate).
4. FILTERS: any filters implied by the question (status, time window, category, etc.), \
including any VALUE HINTS given.
Keep it under 6 lines total. Do not write SQL."""


@dataclass
class PlanResult:
    text: str


class Planner:
    def __init__(self, provider: Provider):
        self.provider = provider

    def plan(self, question: str, schema_context: str, value_hints: str = "") -> PlanResult:
        user = f"SCHEMA:\n{schema_context}\n\n{value_hints}\n\nQUESTION: {question}"
        resp = self.provider.generate(SYSTEM_PROMPT, user, max_tokens=250, temperature=0.0)
        return PlanResult(text=resp.text.strip())
