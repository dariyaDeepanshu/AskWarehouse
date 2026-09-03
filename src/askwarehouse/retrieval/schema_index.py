"""Lexical schema retrieval: never hand the model the whole schema.

The original build embedded every table and column with a sentence-transformer
and ranked by cosine similarity. That needs PyTorch, which does not fit in a
serverless bundle, so this version uses BM25 over the same text (table
description + column descriptions + sample values, and each column on its
own). A table's score is the max of its own score and its best column's
score, so a question that names a specific attribute ("customer email")
still surfaces the right table even when the table-level text doesn't
mention that word. The public API (retrieve / render_prompt_schema /
render_full_schema) is unchanged, so the agent and the eval harness don't
care which backend is in use.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass

from askwarehouse.retrieval.catalog import TableInfo, build_catalog

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        out.append(raw)
        # also index the pieces of snake_case / joined identifiers so
        # "customer revenue" matches "metric_customer_revenue"
        parts = [p for p in _SPLIT_RE.split(raw.replace("_", " ")) if p]
        if len(parts) > 1:
            out.extend(parts)
    return out


def _table_text(t: TableInfo) -> str:
    parts = [f"{t.name} {t.name} {t.description}"]
    for c in t.columns:
        seg = f"{c.name} {c.description}"
        if c.sample_values:
            seg += " " + " ".join(str(v) for v in c.sample_values[:5])
        parts.append(seg)
    return " ".join(parts)


def _column_text(t: TableInfo, c) -> str:
    seg = f"{t.name} {c.name} {c.description}"
    if c.sample_values:
        seg += " " + " ".join(str(v) for v in c.sample_values[:5])
    return seg


class _BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.n = len(docs)
        self.doc_len = [len(d) for d in docs]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.tf = [Counter(d) for d in docs]
        df: Counter = Counter()
        for d in self.tf:
            df.update(d.keys())
        self.idf = {
            term: math.log(1 + (self.n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def score(self, query_terms: list[str], i: int) -> float:
        if not self.avgdl:
            return 0.0
        tf, dl = self.tf[i], self.doc_len[i]
        s = 0.0
        for term in query_terms:
            f = tf.get(term, 0)
            if not f:
                continue
            idf = self.idf.get(term, 0.0)
            s += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s


@dataclass
class RetrievedTable:
    table: TableInfo
    score: float
    matched_columns: list  # list[(ColumnInfo, float)] sorted desc, informational only


class SchemaIndex:
    def __init__(self, tables: list[TableInfo] | None = None):
        self.tables = tables if tables is not None else build_catalog()

        self._table_bm25 = _BM25([_tokenize(_table_text(t)) for t in self.tables])

        self._col_meta: list[tuple[int, object]] = []
        col_docs: list[list[str]] = []
        for ti, t in enumerate(self.tables):
            for c in t.columns:
                self._col_meta.append((ti, c))
                col_docs.append(_tokenize(_column_text(t, c)))
        self._col_bm25 = _BM25(col_docs)

    def retrieve(self, question: str, top_k: int = 4, min_score: float = 0.0) -> list[RetrievedTable]:
        q = _tokenize(question)

        table_scores = [self._table_bm25.score(q, i) for i in range(len(self.tables))]
        col_scores = [self._col_bm25.score(q, i) for i in range(len(self._col_meta))]

        per_table_cols: dict[int, list] = {i: [] for i in range(len(self.tables))}
        for (ti, c), s in zip(self._col_meta, col_scores):
            per_table_cols[ti].append((c, float(s)))

        # normalize so table-level and column-level scores are comparable
        max_t = max(table_scores) or 1.0
        max_c = max(col_scores) if col_scores else 1.0
        max_c = max_c or 1.0

        results = []
        for ti, t in enumerate(self.tables):
            best_col = max((s for _, s in per_table_cols[ti]), default=0.0)
            score = max(table_scores[ti] / max_t, best_col / max_c)
            matched = sorted(per_table_cols[ti], key=lambda x: -x[1])[:5]
            results.append(RetrievedTable(table=t, score=score, matched_columns=matched))

        results.sort(key=lambda r: -r.score)
        strong = [r for r in results if r.score > min_score]
        return (strong or results)[:top_k]

    def render_prompt_schema(self, question: str, top_k: int = 4) -> str:
        retrieved = self.retrieve(question, top_k=top_k)
        return "\n\n".join(r.table.to_prompt_block() for r in retrieved)

    def render_full_schema(self) -> str:
        """Dumps every table in the index into the prompt -- the
        'single-shot, full schema' ablation baseline (no retrieval)."""
        return "\n\n".join(t.to_prompt_block() for t in self.tables)
