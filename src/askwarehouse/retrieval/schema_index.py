"""Embedding-based schema retrieval: never hand the model the whole schema.
Embeds each table's description + column descriptions + sample values, and
each individual column's description + sample values, with sentence-
transformers. At query time, a table's relevance score is the max of its own
embedding similarity and its best column's similarity, so a question that
names a specific attribute ("customer email") surfaces the right table even
if the table-level description doesn't happen to mention that word."""
from dataclasses import dataclass

import numpy as np

from askwarehouse.retrieval.catalog import TableInfo, build_catalog

EMBEDDING_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL_ID)
    return _model


def _table_text(t: TableInfo) -> str:
    parts = [f"{t.name}: {t.description}"]
    for c in t.columns:
        seg = f"{c.name} ({c.data_type}): {c.description}"
        if c.sample_values:
            seg += " examples: " + ", ".join(str(v) for v in c.sample_values[:5])
        parts.append(seg)
    return "\n".join(parts)


def _column_text(t: TableInfo, c) -> str:
    seg = f"{t.name}.{c.name}: {c.description}"
    if c.sample_values:
        seg += " examples: " + ", ".join(str(v) for v in c.sample_values[:5])
    return seg


@dataclass
class RetrievedTable:
    table: TableInfo
    score: float
    matched_columns: list  # list[(ColumnInfo, float)] sorted desc, informational only


class SchemaIndex:
    def __init__(self, tables: list[TableInfo] | None = None):
        self.tables = tables if tables is not None else build_catalog()
        model = _get_model()

        self._table_embeds = model.encode(
            [_table_text(t) for t in self.tables], normalize_embeddings=True
        )

        self._col_meta = []  # list[(table_idx, ColumnInfo)]
        col_texts = []
        for ti, t in enumerate(self.tables):
            for c in t.columns:
                self._col_meta.append((ti, c))
                col_texts.append(_column_text(t, c))
        self._col_embeds = (
            model.encode(col_texts, normalize_embeddings=True) if col_texts else np.zeros((0, 384))
        )

    def retrieve(self, question: str, top_k: int = 4, min_score: float = 0.15) -> list[RetrievedTable]:
        model = _get_model()
        q = model.encode([question], normalize_embeddings=True)[0]

        table_scores = self._table_embeds @ q  # cosine sim, since both normalized
        col_scores = self._col_embeds @ q if len(self._col_embeds) else np.array([])

        per_table_cols: dict[int, list] = {i: [] for i in range(len(self.tables))}
        for (ti, c), s in zip(self._col_meta, col_scores):
            per_table_cols[ti].append((c, float(s)))

        results = []
        for ti, t in enumerate(self.tables):
            best_col_score = max((s for _, s in per_table_cols[ti]), default=0.0)
            score = max(float(table_scores[ti]), best_col_score)
            matched = sorted(per_table_cols[ti], key=lambda x: -x[1])[:5]
            results.append(RetrievedTable(table=t, score=score, matched_columns=matched))

        results.sort(key=lambda r: -r.score)
        results = [r for r in results if r.score >= min_score] or results[:1]
        return results[:top_k]

    def render_prompt_schema(self, question: str, top_k: int = 4) -> str:
        retrieved = self.retrieve(question, top_k=top_k)
        return "\n\n".join(r.table.to_prompt_block() for r in retrieved)

    def render_full_schema(self) -> str:
        """Dumps every table in the index into the prompt -- the
        'single-shot, full schema' ablation baseline (no retrieval)."""
        return "\n\n".join(t.to_prompt_block() for t in self.tables)
