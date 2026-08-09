"""Generic embedding-based value index for BIRD databases -- the same
mechanism as retrieval/value_index.py's fallback path (fuzzy nearest-
neighbor over distinct categorical values), but without the deterministic
alias-table half, since there's no reference mapping table (like our
us_states seed) available for an arbitrary external database. This is
intentionally the weaker, "no curated reference data" condition."""
import re
import sqlite3
from dataclasses import dataclass

import numpy as np

from askwarehouse.retrieval.schema_index import _get_model
from askwarehouse.retrieval.value_index import STOPWORDS

MAX_CARDINALITY = 300


@dataclass
class ValueHint:
    table: str
    column: str
    value: str
    matched_phrase: str
    score: float


class BirdValueIndex:
    def __init__(self, db_path: str):
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
            meta, values_to_embed = [], []
            for table in tables:
                cols = con.execute(f'PRAGMA table_info("{table}")').fetchall()
                for _cid, col_name, data_type, *_ in cols:
                    if (data_type or "").upper() not in ("TEXT", "VARCHAR", "CHAR", ""):
                        continue
                    try:
                        n = con.execute(f'SELECT COUNT(DISTINCT "{col_name}") FROM "{table}"').fetchone()[0]
                        if not n or n > MAX_CARDINALITY:
                            continue
                        vals = [r[0] for r in con.execute(
                            f'SELECT DISTINCT "{col_name}" FROM "{table}" WHERE "{col_name}" IS NOT NULL'
                        ).fetchall()]
                    except sqlite3.Error:
                        continue
                    for v in vals:
                        if v is None or str(v).strip() == "":
                            continue
                        meta.append((table, col_name, str(v)))
                        values_to_embed.append(str(v))
            self._meta = meta
            self._embeds = _get_model().encode(values_to_embed, normalize_embeddings=True) if values_to_embed else np.zeros((0, 384))
        finally:
            con.close()

    def _candidate_phrases(self, question: str) -> list:
        words = re.findall(r"[A-Za-z0-9']+", question)
        phrases = set()
        for n in (1, 2, 3):
            for i in range(len(words) - n + 1):
                span = words[i:i + n]
                if all(w.lower() in STOPWORDS for w in span):
                    continue
                phrases.add(" ".join(span))
        return list(phrases)

    def lookup(self, question: str, threshold: float = 0.62, max_hints: int = 6) -> list:
        if len(self._embeds) == 0:
            return []
        phrases = self._candidate_phrases(question)
        if not phrases:
            return []
        model = _get_model()
        phrase_embeds = model.encode(phrases, normalize_embeddings=True)
        sims = phrase_embeds @ self._embeds.T
        best_idx = sims.argmax(axis=1)
        best_score = sims.max(axis=1)
        seen, hints = set(), []
        for phrase, idx, score in zip(phrases, best_idx, best_score):
            if score < threshold:
                continue
            table, column, value = self._meta[idx]
            key = (table, column, value)
            if key in seen:
                continue
            seen.add(key)
            hints.append(ValueHint(table=table, column=column, value=value, matched_phrase=phrase, score=float(score)))
        hints.sort(key=lambda h: -h.score)
        return hints[:max_hints]

    def render_prompt_hints(self, question: str) -> str:
        hints = self.lookup(question)
        if not hints:
            return ""
        lines = ["VALUE HINTS (literal -> stored value; use these exact stored values in filters):"]
        for h in hints:
            lines.append(f"  \"{h.matched_phrase}\" -> {h.table}.{h.column} = '{h.value}'  (score={h.score:.2f})")
        return "\n".join(lines)
