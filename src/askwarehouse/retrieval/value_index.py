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
  2. Fuzzy string matching over the distinct values of every other
     low-cardinality categorical column (order_status, channel, brand, ...),
     for cases where there's no clean reference table. The original build
     used sentence-transformer nearest-neighbour here; this version uses
     token-overlap + difflib ratio, which is pure-stdlib and works well for
     the short single-token categorical values these columns actually hold.
"""
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

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
    method: str  # 'alias' | 'fuzzy'
    score: float


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _similarity(phrase: str, value: str) -> float:
    """1.0 for an exact (normalized) match, a high score when one string's
    tokens are a subset of the other's, else a character-level ratio."""
    p, v = _norm(phrase), _norm(value)
    if not p or not v:
        return 0.0
    if p == v:
        return 1.0
    pt, vt = set(p.split()), set(v.split())
    if pt and vt and (pt <= vt or vt <= pt):
        return 0.92
    if pt & vt:
        overlap = len(pt & vt) / max(len(pt), len(vt))
        return 0.6 + 0.3 * overlap
    return SequenceMatcher(None, p, v).ratio()


class ValueIndex:
    def __init__(self, config: SafetyConfig = DEFAULT_SAFETY_CONFIG):
        self.config = config
        self.alias_map: dict[str, str] = {}       # lowercase full name -> code
        self.alias_columns: list[tuple[str, str]] = []  # (table, column) pairs the alias applies to
        self._values: list[tuple[str, str, str]] = []   # (table, column, value)
        self._build()

    def _build(self):
        with readonly_connection(self.config) as con:
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

            candidate_cols = con.execute(
                """SELECT table_schema, table_name, column_name
                   FROM information_schema.columns
                   WHERE table_schema = ANY(?) AND data_type = 'VARCHAR'
                     AND column_name NOT IN ('state_code', 'state_name')""",
                [list(self.config.allowed_schemas)],
            ).fetchall()

            for schema, table, column, *_ in candidate_cols:
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
                    self._values.append((table, column, str(v)))

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

    def lookup(self, question: str, fuzzy_threshold: float = 0.82, max_hints: int = 6) -> list[ValueHint]:
        hints: list[ValueHint] = []
        q_lower = question.lower()
        alias_resolved_phrases: set[str] = set()

        # 1. deterministic alias matches
        for full_name, code in self.alias_map.items():
            if re.search(rf"\b{re.escape(full_name)}\b", q_lower):
                alias_resolved_phrases.add(full_name)
                for table, column in self.alias_columns:
                    if table == "us_states":
                        continue
                    hints.append(ValueHint(
                        table=table, column=column, value=code,
                        matched_phrase=full_name, method="alias", score=1.0,
                    ))

        # 2. fuzzy match over general categorical values
        phrases = self._candidate_phrases(question)
        seen: set[tuple] = set()
        for phrase in phrases:
            if phrase.lower() in alias_resolved_phrases:
                continue
            best = None
            for table, column, value in self._values:
                sc = _similarity(phrase, value)
                if best is None or sc > best[0]:
                    best = (sc, table, column, value)
            if best and best[0] >= fuzzy_threshold:
                sc, table, column, value = best
                key = (table, column, value)
                if key in seen:
                    continue
                seen.add(key)
                hints.append(ValueHint(
                    table=table, column=column, value=value,
                    matched_phrase=phrase, method="fuzzy", score=float(sc),
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
