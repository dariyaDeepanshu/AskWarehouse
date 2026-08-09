"""The value index: resolves a literal phrase in the question ("California")
to the actual stored value in a column ("CA") *before* SQL generation, so
the model is told the mapping instead of having to guess it (or getting it
wrong and relying on the repair loop to notice a query that ran fine but
silently returned zero rows).

Two mechanisms, deliberately kept separate:

  1. Alias tables -- deterministic, sourced from a reference mapping (here:
     the us_states dbt seed) and applied to every column that is known to
     store the coded form (state_code). This is the flagship case: some
     columns (dim_stores.state_code) have NO friendly-name column to fall
     back on, so without this the model has to guess 'CA' from "California"
     with nothing but its own world knowledge.
  2. A general embedding index over the distinct values of every other
     low-cardinality categorical column (order_status, channel, brand, ...),
     for cases where there's no clean reference table -- just fuzzy nearest-
     neighbor matching between a phrase in the question and a stored value.
"""
import re
from dataclasses import dataclass

import numpy as np

from askwarehouse.execution.connection import readonly_connection
from askwarehouse.safety.config import SafetyConfig, DEFAULT_SAFETY_CONFIG, PII_DENYLIST

MAX_CARDINALITY = 500
STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "by", "for", "to", "and", "or", "is", "are",
    "what", "which", "who", "how", "many", "much", "top", "last", "this", "that",
    "show", "me", "list", "with", "was", "were", "did", "do", "does", "over", "per",
}


@dataclass
class ValueHint:
    table: str
    column: str
    value: str
    matched_phrase: str
    method: str  # 'alias' | 'embedding'
    score: float


def _get_model():
    from askwarehouse.retrieval.schema_index import _get_model as g
    return g()


class ValueIndex:
    def __init__(self, config: SafetyConfig = DEFAULT_SAFETY_CONFIG):
        self.config = config
        self.alias_map: dict[str, str] = {}       # lowercase full name -> code
        self.alias_columns: list[tuple[str, str]] = []  # (table, column) pairs the alias applies to
        self._value_meta: list[tuple[str, str, str]] = []  # (table, column, value)
        self._value_embeds = np.zeros((0, 384))
        self._build()

    def _build(self):
        with readonly_connection(self.config) as con:
            # 1. alias table from the us_states seed
            try:
                rows = con.execute("SELECT state_name, state_code FROM main.us_states").fetchall()
                self.alias_map = {name.lower(): code for name, code in rows}
            except Exception:
                self.alias_map = {}

            for schema in self.config.allowed_schemas:
                cols = con.execute(
                    """SELECT table_name, column_name FROM information_schema.columns
                       WHERE table_schema = ? AND column_name = 'state_code'""",
                    [schema],
                ).fetchall()
                self.alias_columns.extend([(t, c) for t, c in cols])

            # 2. general embedding index over other low-cardinality VARCHAR columns
            candidate_cols = con.execute(
                """SELECT table_schema, table_name, column_name, data_type
                   FROM information_schema.columns
                   WHERE table_schema = ANY(?) AND data_type = 'VARCHAR'
                     AND column_name NOT IN ('state_code', 'state_name')""",
                [list(self.config.allowed_schemas)],
            ).fetchall()

            values_to_embed, meta = [], []
            for schema, table, column, _dtype in candidate_cols:
                if (table, column) in PII_DENYLIST:
                    continue
                try:
                    n = con.execute(
                        f'SELECT approx_count_distinct("{column}") FROM {schema}.{table}'
                    ).fetchone()[0]
                    if not n or n > MAX_CARDINALITY:
                        continue
                    distinct_vals = [
                        r[0] for r in con.execute(
                            f'SELECT DISTINCT "{column}" FROM {schema}.{table} WHERE "{column}" IS NOT NULL'
                        ).fetchall()
                    ]
                except Exception:
                    continue
                for v in distinct_vals:
                    values_to_embed.append(str(v))
                    meta.append((table, column, str(v)))

            self._value_meta = meta
            if values_to_embed:
                self._value_embeds = _get_model().encode(values_to_embed, normalize_embeddings=True)

    def _candidate_phrases(self, question: str) -> list[str]:
        words = re.findall(r"[A-Za-z']+", question)
        phrases = set()
        for n in (1, 2, 3):
            for i in range(len(words) - n + 1):
                span = words[i:i + n]
                if all(w.lower() in STOPWORDS for w in span):
                    continue
                phrases.add(" ".join(span))
        return list(phrases)

    def lookup(self, question: str, embedding_threshold: float = 0.62, max_hints: int = 6) -> list[ValueHint]:
        hints: list[ValueHint] = []
        q_lower = question.lower()
        alias_resolved_phrases: set[str] = set()

        # 1. deterministic alias matches
        for full_name, code in self.alias_map.items():
            if re.search(rf"\b{re.escape(full_name)}\b", q_lower):
                alias_resolved_phrases.add(full_name)
                for table, column in self.alias_columns:
                    if table == "us_states":
                        continue  # that's the alias source itself, not a queryable fact/dim
                    hints.append(ValueHint(
                        table=table, column=column, value=code,
                        matched_phrase=full_name, method="alias", score=1.0,
                    ))

        # 2. embedding nearest-neighbor over general categorical values
        if len(self._value_embeds):
            phrases = self._candidate_phrases(question)
            if phrases:
                model = _get_model()
                phrase_embeds = model.encode(phrases, normalize_embeddings=True)
                sims = phrase_embeds @ self._value_embeds.T  # [n_phrases, n_values]
                best_idx = sims.argmax(axis=1)
                best_score = sims.max(axis=1)
                seen = set()
                for phrase, idx, score in zip(phrases, best_idx, best_score):
                    if score < embedding_threshold:
                        continue
                    if phrase.lower() in alias_resolved_phrases:
                        continue
                    table, column, value = self._value_meta[idx]
                    key = (table, column, value)
                    if key in seen:
                        continue
                    seen.add(key)
                    hints.append(ValueHint(
                        table=table, column=column, value=value,
                        matched_phrase=phrase, method="embedding", score=float(score),
                    ))

        hints.sort(key=lambda h: -h.score)
        return hints[:max_hints]

    def render_prompt_hints(self, question: str) -> str:
        hints = self.lookup(question)
        if not hints:
            return ""
        lines = ["VALUE HINTS (literal -> stored value; use these exact stored values in filters):"]
        for h in hints:
            lines.append(f"  \"{h.matched_phrase}\" -> {h.table}.{h.column} = '{h.value}'  "
                          f"({h.method}, score={h.score:.2f})")
        return "\n".join(lines)
